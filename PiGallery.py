import os
import dropbox
import tkinter
import random
import json
import time

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

FADE_IMAGES = False

LABEL_MONITOR_INDEX = 0
PHOTO_MONITOR_INDEX = 1

REFRESH_RATE_MS = 500
IMAGE_SWAP_RATE_MS = (10 * 1000)

root = tkinter.Tk()
root.bind("<Escape>", lambda e: root.destroy())  # (e.widget.withdraw(), e.widget.quit()))
root.bind("<Right>", lambda e: force_refresh())
root.withdraw()

swap_counter = 0
swap_pause = False

canvas_photo = None
canvas_label = None
canvas_img_photo = None
canvas_img_label = None
pil_img_photo = None
pil_img_label = None


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
    window.bind("<Escape>", lambda e: root.destroy())  # (e.widget.withdraw(), e.widget.quit()))
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
    dbx = dropbox_connect()

    try:
        dbx.files_download_to_file(path=dropbox_path, download_path=local_path)
        return Image.open(local_path)
    except Exception as e:
        print('Error getting list of files from Dropbox: ' + str(e))


def dropbox_get_random_json():
    dbx = dropbox_connect()

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

    #file = random.choice(dbx.files_list_folder("/jsons").entries)
    file_path = f'/jsons/{file.name}'
    dbx.files_download_to_file(path=file_path, download_path='temp/subject.json')
    json_obj = json.load(open('temp/subject.json'))
    return json_obj


def dropbox_get_num_jsons():
    dbx = dropbox_connect()

    count = 0;
    for i in dbx.files_list_folder("/jsons").entries:
        count += 1
    return count


def get_pdf_fields(image, subject_json, image_json):
    exif = {ExifTags.TAGS[k]: v for k, v in image._getexif().items() if k in ExifTags.TAGS}
    # print(exif)

    date_taken_obj = datetime.strptime(exif['DateTimeOriginal'], '%Y:%m:%d %H:%M:%S')
    date_taken_str = date_taken_obj.strftime('%#I:%M %p %B %#d, %Y')

    camera_body = exif['Model']
    focal_length = exif['FocalLength']
    aperture = exif['FNumber']
    shutter = 1 / exif['ExposureTime']
    iso = exif['ISOSpeedRatings']

    name = subject_json['name']
    if len(image_json['name_detail']) > 0:
        name = f'{name} ({image_json["name_detail"]})'

    filled_fields = {
        "Title": name,
        "Subtitle": subject_json['species'],
        "Date": date_taken_str,
        "Location": image_json['location'],
        "Body": f'{camera_body} at {focal_length}mm',
        "Exposure": f'1/{shutter}s at f/{aperture}, {iso} ISO',
    }
    return filled_fields


def get_filled_pdf_as_image(image, subject_json, image_json):
    dbx = dropbox_connect()
    dbx.files_download_to_file(path=image_json['label_template'], download_path='temp/template.pdf')

    filled_fields = get_pdf_fields(image, subject_json, image_json)
    fillpdfs.write_fillable_pdf('temp/template.pdf', 'temp/label.pdf', filled_fields)
    pdf_as_img = convert_from_path('temp/label.pdf', use_cropbox=True)
    pdf_as_img[0].save('temp/label.jpg', 'JPEG')
    return Image.open('temp/label.jpg')


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

            global canvas_photo, canvas_label, canvas_img_photo, canvas_img_label, pil_img_photo, pil_img_label

            # get random subject JSON
            subject_json = dropbox_get_random_json()
            # choose random photo for the subject
            image_json = random.choice(subject_json['images'])

            print(f'subject: {subject_json["name"]}')
            print(f'image: {image_json["photo"]}\n')

            # download the photo
            pil_img_photo = dropbox_get_file(image_json['photo'], 'temp/test.jpg')
            # fill label template PDF with info from the subject's JSON, and download it as an image
            pil_img_label = get_filled_pdf_as_image(pil_img_photo, subject_json, image_json)
            # swap to new images
            if FADE_IMAGES:
                fade_images(FadeDirection.IN)
            else:
                canvas_img_photo = update_canvas_image(canvas_photo, pil_img_photo, PHOTO_MONITOR_INDEX)
                canvas_img_label = update_canvas_image(canvas_label, pil_img_label, LABEL_MONITOR_INDEX)

            swap_counter = 0
            swap_pause = False


def fade_images(fade_direction):
    global canvas_photo, canvas_label, canvas_img_photo, canvas_img_label, pil_img_photo, pil_img_label

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
        pil_img_label.putalpha(i)
        canvas_img_photo = update_canvas_image(canvas_photo, pil_img_photo, PHOTO_MONITOR_INDEX)
        canvas_img_label = update_canvas_image(canvas_label, pil_img_label, LABEL_MONITOR_INDEX)
        canvas_photo.update()
        canvas_label.update()
        # Sleep some time to make the transition not immediate
        time.sleep(0.01)


if __name__ == '__main__':
    # make temp folder for downloading files to
    if not os.path.exists('temp'):
        os.mkdir('temp')

    # get random subject JSON
    subject_json = dropbox_get_random_json()
    # choose random photo for the subject
    image_json = random.choice(subject_json['images'])

    print(f'subject: {subject_json["name"]}')
    print(f'image: {image_json["photo"]}\n')

    # download the photo
    pil_img_photo = dropbox_get_file(image_json['photo'], 'temp/test.jpg')
    # fill label template PDF with info from the subject's JSON, and download it as an image
    pil_img_label = get_filled_pdf_as_image(pil_img_photo, subject_json, image_json)

    # create Tkinter windows to display the image & the label
    win1 = tkinter.Toplevel(root)
    win2 = tkinter.Toplevel(root)

    # open the images
    canvas_photo, canvas_img_photo = open_image_fullscreen(win1, pil_img_photo, PHOTO_MONITOR_INDEX)
    canvas_label, canvas_img_label = open_image_fullscreen(win2, pil_img_label, LABEL_MONITOR_INDEX)

    # periodically refresh the images
    while True:
        if not swap_pause:
            root.update()
            root.after(REFRESH_RATE_MS, swap_images())
        time.sleep(.5)

    # run Tkinter
    root.mainloop()
