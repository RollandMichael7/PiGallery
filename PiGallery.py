import os
import dropbox
import tkinter
import random
import json
import time
import argparse, sys

from enum import Enum
from datetime import datetime, timedelta
from fillpdf import fillpdfs
from pdf2image import convert_from_path
from screeninfo import get_monitors
from dropbox.exceptions import AuthError
from dropbox import DropboxOAuth2FlowNoRedirect
from PIL import Image, ImageTk, ExifTags

DROPBOX_APP_KEY = os.environ['PIGALLERY_APP_KEY']
DROPBOX_REFRESH_TOKEN = os.environ['PIGALLERY_REFRESH_TOKEN']

# length of the arrays used to check for repeats
# eg. if PHOTO_BUFFER_LENGTH = 10, then the last 10 randomly selected images will not be selected again
SUBJECT_BUFFER_LENGTH = 0
PHOTO_BUFFER_LENGTH = 30

# max number of retries to get files from dropbox
MAX_RETRIES = 10

FADE_IMAGES = False

PLAQUE_MONITOR_INDEX = 0
PHOTO_MONITOR_INDEX = 1

REFRESH_RATE_MS = 500
IMAGE_SWAP_RATE_MS = (10 * 1000)

# poppler path for using PyMuPDF on Windows
POPPLER_PATH = None

# track how often each subject & image is chosen
subject_image_frequencies = {}

root = tkinter.Tk()
root.bind("<Escape>", lambda e: exit_program())
root.bind("<Right>", lambda e: force_refresh())
root.withdraw()

swap_counter = 0
swap_pause = False

printed_logs = False

canvas_photo = None
canvas_plaque = None
canvas_img_photo = None
canvas_img_plaque = None
pil_img_photo = None
pil_img_plaque = None

subject_buffer = []
photo_buffer = []


class FadeDirection(Enum):
    OUT = 1
    IN = 2


def open_image_fullscreen(window, pil_image, monitor_index):
    monitor_dims = get_monitors()[monitor_index]
    x = monitor_dims.x
    y = monitor_dims.y
    w = monitor_dims.width
    h = monitor_dims.height

    window.overrideredirect(1)
    window.geometry("%dx%d+%d+%d" % (w, h, x, y))
    window.focus_set()    
    window.bind("<Escape>", lambda e: exit_program())
    window.bind("<Right>", lambda e: force_refresh())
    canvas = tkinter.Canvas(window, width=w, height=h)
    canvas.pack()
    canvas.configure(background='black')
    img_width, img_height = pil_image.size
    if img_width > w or img_height > h:
        ratio = min(w/img_width, h/img_height)
        img_width = int(img_width*ratio)
        img_height = int(img_height*ratio)
        pil_image = pil_image.resize((img_width, img_height), Image.ANTIALIAS)
    image = ImageTk.PhotoImage(pil_image)
    image_sprite = canvas.create_image(w/2, h/2, image=image)
    # return the PhotoImage so it doesnt get garbage collected
    return canvas, image


def update_canvas_image(canvas, pil_image, monitor_index):
    monitor_dims = get_monitors()[monitor_index]
    w = monitor_dims.width
    h = monitor_dims.height
    img_width, img_height = pil_image.size
    if img_width > w or img_height > h:
        ratio = min(w / img_width, h / img_height)
        img_width = int(img_width * ratio)
        img_height = int(img_height * ratio)
        pil_image = pil_image.resize((img_width, img_height), Image.ANTIALIAS)
    image = ImageTk.PhotoImage(pil_image)
    canvas.create_image(w/2, h/2, image=image)
    canvas.itemconfigure(image, image=image)
    return image


def dropbox_connect():
    try:
        return dropbox.Dropbox(oauth2_refresh_token=DROPBOX_REFRESH_TOKEN, app_key=DROPBOX_APP_KEY)
    except AuthError as e:
        print('Error connecting to Dropbox with access token: ' + str(e))
        exit_program()


def dropbox_get_refresh_token():
    auth_flow = DropboxOAuth2FlowNoRedirect(DROPBOX_APP_KEY, use_pkce=True, token_access_type='offline')

    authorize_url = auth_flow.start()
    print("1. Go to: " + authorize_url)
    print("2. Click \"Allow\" (you might have to log in first).")
    print("3. Copy the authorization code.")
    auth_code = input("Enter the authorization code here: ").strip()

    try:
        oauth_result = auth_flow.finish(auth_code)
    except Exception as e:
        print('Error: %s' % (e,))
        exit(1)

    return oauth_result.refresh_token


def dropbox_get_file(dropbox_path, local_path):
    global MAX_RETRIES
    num_retries = 0

    while True:
        try:
            dbx = dropbox_connect()
            dbx.files_download_to_file(path=dropbox_path, download_path=local_path)
            return Image.open(local_path)
        except Exception as e:
            print("Error getting file from Dropbox. Retrying...")

            num_retries += 1
            if num_retries >= MAX_RETRIES:
                print("Ran out of retries. Exiting")
                exit_program()
            time.sleep(2)


def dropbox_get_random_json():
    global MAX_RETRIES
    num_retries = 0

    while True:
        try:
            dbx = dropbox_connect()

            # emulated do-while loop to keep trying to select an image until we get one that isnt a repeat of the last N, defined by SUBJECT_BUFFER_LENGTH and PHOTO_BUFFER_LENGTH
            global photo_buffer, subject_buffer
            while True:
                num_files = dropbox_get_num_jsons()
                file_index = random.randint(1, num_files)
                print(f'index: {file_index}')
                index = 1
                file = None
                for i in dbx.files_list_folder("/jsons").entries:
                    if index == file_index:
                        file = i
                        break
                    index += 1

                print(f'file: {file.name}')

                file_path = f'/jsons/{file.name}'
                dbx.files_download_to_file(path=file_path, download_path='temp/subject.json')
                json_obj = json.load(open('temp/subject.json'))

                # if using subject buffer, only select this file if it's not one of the last N we've used
                if SUBJECT_BUFFER_LENGTH > 0 and file.name in subject_buffer:
                    print('Repeat skipped\n')
                    continue

                # if using photo buffer, only select this file if it contains at least one image that's not one of the last N we've used
                if PHOTO_BUFFER_LENGTH > 0:
                    has_valid_image = False
                    for img in json_obj["images"]:
                        if img["photo"] not in photo_buffer:
                            has_valid_image = True
                            break

                    if not has_valid_image:
                        print('No non-repeat images found\n')
                        continue

                if SUBJECT_BUFFER_LENGTH > 0:
                    # add this file to the list of the last N we've used
                    if len(subject_buffer) == SUBJECT_BUFFER_LENGTH:
                        subject_buffer.pop(SUBJECT_BUFFER_LENGTH - 1)
                    subject_buffer.insert(0, file.name)

                break

            return json_obj
        except Exception as e:
            print("Error getting random json. Retrying...")

            num_retries += 1
            if num_retries >= MAX_RETRIES:
                print("Ran out of retries. Exiting")
                exit_program()
            time.sleep(2)


def dropbox_get_num_jsons():
    global MAX_RETRIES
    num_retries = 0

    while True:
        try:
            dbx = dropbox_connect()

            count = 0;
            for i in dbx.files_list_folder("/jsons").entries:
                count += 1
            return count
        except Exception as e:
            print("Error getting json count. Retrying...")

            num_retries += 1
            if num_retries >= MAX_RETRIES:
                print("Ran out of retries. Exiting")
                exit_program()
            time.sleep(2)


def get_pdf_fields(image, subject_json, image_json):
    exif = {ExifTags.TAGS[k]: v for k, v in image._getexif().items() if k in ExifTags.TAGS}
    # print(exif)

    date_taken_obj = datetime.strptime(exif['DateTimeOriginal'], '%Y:%m:%d %H:%M:%S')

    # portable way to get datetime without leading zeroes, since strftime isnt portable...
    hour = int(date_taken_obj.strftime('%I'))
    minute = date_taken_obj.strftime('%M')
    period = date_taken_obj.strftime('%p')
    month = date_taken_obj.strftime('%B')
    day = int(date_taken_obj.strftime('%d'))
    year = date_taken_obj.strftime('%Y')

    camera_body = exif['Model']
    focal_length = int(exif['FocalLength'])
    aperture = exif['FNumber']
    shutter = 1 / exif['ExposureTime']
    iso = exif['ISOSpeedRatings']

    name = subject_json['name']
    if len(image_json['name_detail']) > 0:
        name = f'{name} ({image_json["name_detail"]})'

    filled_fields = {
        "Title": name,
        "Subtitle": subject_json['species'],
        "Date": f'{hour}:{minute} {period} {month} {day}, {year}',
        "Location": image_json['location'],
        "Body": f'{camera_body} at {focal_length}mm',
        "Exposure": f'1/{shutter}s at f/{aperture}, {iso} ISO',
    }
    return filled_fields


def get_filled_pdf_as_image(image, subject_json, image_json):
    global MAX_RETRIES
    num_retries = 0

    while True:
        try:
            global POPPLER_PATH
            dbx = dropbox_connect()
            dbx.files_download_to_file(path=image_json['plaque_template'], download_path='temp/template.pdf')

            filled_fields = get_pdf_fields(image, subject_json, image_json)
            fillpdfs.write_fillable_pdf('temp/template.pdf', 'temp/plaque.pdf', filled_fields)

            if POPPLER_PATH is not None:
                pdf_as_img = convert_from_path('temp/plaque.pdf', use_cropbox=True, poppler_path=POPPLER_PATH)
            else:
                pdf_as_img = convert_from_path('temp/plaque.pdf', use_cropbox=True)
            
            pdf_as_img[0].save('temp/plaque.jpg', 'JPEG')
            return Image.open('temp/plaque.jpg')
        except Exception as e:
            print("Error getting plaque PDF. Retrying...")

            num_retries += 1
            if num_retries >= MAX_RETRIES:
                print("Ran out of retries. Exiting")
                exit_program()
            time.sleep(2)


def force_refresh():
    print('force refresh')
    global swap_counter
    swap_counter = IMAGE_SWAP_RATE_MS
    swap_images()


def swap_images():
    global swap_counter, swap_pause

    if not swap_pause:
        swap_counter += REFRESH_RATE_MS + 500
        if swap_counter >= IMAGE_SWAP_RATE_MS:
            swap_pause = True

            if FADE_IMAGES:
                fade_images(FadeDirection.OUT)

            global photo_buffer, canvas_photo, canvas_plaque, canvas_img_photo, canvas_img_plaque, pil_img_photo, pil_img_plaque

            # get random subject JSON
            subject_json = dropbox_get_random_json()
            # emulated do-while loop to choose random photo for the subject that isn't one of the last N we've already used
            while True:
                image_json = random.choice(subject_json["images"])
                if PHOTO_BUFFER_LENGTH > 0:
                    if image_json["photo"] not in photo_buffer:
                        # add this file to the list of the last N we've used
                        if len(photo_buffer) == PHOTO_BUFFER_LENGTH:
                            photo_buffer.pop(PHOTO_BUFFER_LENGTH - 1)
                        photo_buffer.insert(0, image_json["photo"])
                        break
                    else:
                        print("Repeat skipped")
                else:
                    break

            log_image(subject_json, image_json)
            print(f'subject: {subject_json["name"]}')
            print(f'image: {image_json["photo"]}\n')

            # download the photo
            pil_img_photo = dropbox_get_file(image_json["photo"], 'temp/test.jpg')
            # fill plaque template PDF with info from the subject's JSON, and download it as an image
            pil_img_plaque = get_filled_pdf_as_image(pil_img_photo, subject_json, image_json)
            # swap to new images
            if FADE_IMAGES:
                fade_images(FadeDirection.IN)
            else:
                canvas_img_photo = update_canvas_image(canvas_photo, pil_img_photo, PHOTO_MONITOR_INDEX)
                canvas_img_plaque = update_canvas_image(canvas_plaque, pil_img_plaque, PLAQUE_MONITOR_INDEX)

            swap_counter = 0
            swap_pause = False


def fade_images(fade_direction):
    global canvas_photo, canvas_plaque, canvas_img_photo, canvas_img_plaque, pil_img_photo, pil_img_plaque

    from_opacity = to_opacity = step = 0
    if fade_direction == FadeDirection.OUT:
        from_opacity = 255
        to_opacity = 0
        step = -50
    else:
        from_opacity = 0
        to_opacity = 255
        step = 50

    for i in range(from_opacity, to_opacity, step):
        pil_img_photo.putalpha(i)
        pil_img_plaque.putalpha(i)
        canvas_img_photo = update_canvas_image(canvas_photo, pil_img_photo, PHOTO_MONITOR_INDEX)
        canvas_img_plaque = update_canvas_image(canvas_plaque, pil_img_plaque, PLAQUE_MONITOR_INDEX)
        canvas_photo.update()
        canvas_plaque.update()
        # Sleep some time to make the transition not immediate
        time.sleep(0.01)


def log_image(subject_json, image_json):
    global subject_image_frequencies
    subject = subject_json["name"]
    image = image_json["photo"] 
    
    if subject in subject_image_frequencies and image in subject_image_frequencies[subject]:
        curr = subject_image_frequencies[subject][image]
        subject_image_frequencies[subject][image] = curr + 1
    elif subject in subject_image_frequencies:
        subject_image_frequencies[subject][image] = 1
    else:
        subject_image_frequencies[subject] = {}
        subject_image_frequencies[subject][image] = 1



def exit_program():
    global printed_logs

    if not printed_logs:
        # log frequency of selected images before we exit
        printed_logs = True
        print("\nImage frequencies\n")

        global subject_image_frequencies
        
        subject_frequencies = []
        total_images = 0
        for subject in subject_image_frequencies.keys():
            print(f'Subject: {subject}')

            subject_frequency = 0
            image_count = 0
            for image in subject_image_frequencies[subject].keys():
                image_frequency = subject_image_frequencies[subject][image]
                subject_frequency += image_frequency
                image_count += 1
                total_images += image_frequency
                print(f'{image}: {image_frequency}')
            print(f'Total: {subject_frequency}\n')
            subject_frequencies.append({"subject": subject, "count": subject_frequency, "image_count": image_count})

        print(f'Totals\n')
        for s in sorted(subject_frequencies, key=lambda x: x["count"], reverse=True):
            print(f'{s["subject"]}: {s["count"]} [{s["image_count"]} images]')
        print(f'Total: {total_images}')

        global root
        root.destroy()
        exit(0)


def read_args(args):
    global SUBJECT_BUFFER_LENGTH, PHOTO_BUFFER_LENGTH, IMAGE_SWAP_RATE_MS, PHOTO_MONITOR_INDEX, PLAQUE_MONITOR_INDEX, POPPLER_PATH, FADE_IMAGES, MAX_RETRIES

    if args.SUBJECT_BUFFER_LENGTH is not None:
        SUBJECT_BUFFER_LENGTH = int(args.SUBJECT_BUFFER_LENGTH)

    if args.PHOTO_BUFFER_LENGTH is not None:
        PHOTO_BUFFER_LENGTH = int(args.PHOTO_BUFFER_LENGTH)

    if args.IMAGE_SWAP_RATE_MS is not None:
        IMAGE_SWAP_RATE_MS = int(args.IMAGE_SWAP_RATE_MS)

    if args.PHOTO_MONITOR_INDEX is not None:
        PHOTO_MONITOR_INDEX = int(args.PHOTO_MONITOR_INDEX)

    if args.PLAQUE_MONITOR_INDEX is not None:
        PLAQUE_MONITOR_INDEX = int(args.PLAQUE_MONITOR_INDEX)

    if args.POPPLER_PATH is not None:
        POPPLER_PATH = args.POPPLER_PATH

    if args.FADE_IMAGES is not None:
        FADE_IMAGES = bool(args.FADE_IMAGES)

    if args.MAX_RETRIES is not None:
        MAX_RETRIES = int(args.MAX_RETRIES)


if __name__ == '__main__':
    try:
        parser = argparse.ArgumentParser()
        parser.add_argument("--SUBJECT_BUFFER_LENGTH", help='Number of last photo subjects to not repeat')
        parser.add_argument("--PHOTO_BUFFER_LENGTH", help='Number of last photos to not repeat')
        parser.add_argument("--IMAGE_SWAP_RATE_MS", help='Frequency of image swaps, in ms')
        parser.add_argument("--PHOTO_MONITOR_INDEX", help='Index of the monitor for displaying the photo')
        parser.add_argument("--PLAQUE_MONITOR_INDEX", help='Index of the monitor for displaying the plaque')
        parser.add_argument("--POPPLER_PATH", help='Path to Poppler bin folder, required for using PyMuPDF on Windows')
        parser.add_argument("--FADE_IMAGES", help='Whether to fade images in & out while swapping')
        parser.add_argument("--MAX_RETRIES", help='Max amount of attempts to get a file from Dropbox app')

        args = parser.parse_args()
        read_args(args)

        # make temp folder for downloading files to
        if not os.path.exists('temp'):
            os.mkdir('temp')

        # get random subject JSON
        subject_json = dropbox_get_random_json()
        # choose random photo for the subject
        image_json = random.choice(subject_json["images"])

        log_image(subject_json, image_json)

        # store image name in buffer so it isnt repeated
        if PHOTO_BUFFER_LENGTH > 0:
            photo_buffer.insert(0, image_json["photo"])

        print(f'subject: {subject_json["name"]}')
        print(f'image: {image_json["photo"]}\n')

        # download the photo
        pil_img_photo = dropbox_get_file(image_json['photo'], 'temp/test.jpg')
        # fill plaque template PDF with info from the subject's JSON, and download it as an image
        pil_img_plaque = get_filled_pdf_as_image(pil_img_photo, subject_json, image_json)

        # create Tkinter windows to display the image & the plaque
        win1 = tkinter.Toplevel(root)
        win2 = tkinter.Toplevel(root)

        # open the images
        canvas_photo, canvas_img_photo = open_image_fullscreen(win1, pil_img_photo, PHOTO_MONITOR_INDEX)
        canvas_plaque, canvas_img_plaque = open_image_fullscreen(win2, pil_img_plaque, PLAQUE_MONITOR_INDEX)

        # periodically refresh the images
        while True:
            if not swap_pause:
                root.update()
                root.after(REFRESH_RATE_MS, swap_images())
            time.sleep(.5)

        # run Tkinter
        root.mainloop()
    except Exception as e:
        exit_program()
