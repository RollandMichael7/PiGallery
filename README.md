# PiGallery
Python script to display a photo along with a "plaque" with details about the photo.

Photos, PDF templates for the plaque, and JSONs with data for the plaque are pulled live from a Dropbox app and shuffled through on a set interval.

![demo](https://user-images.githubusercontent.com/14168201/178127631-84a20187-7b9c-462a-9ea7-feb666d98ebe.gif)

[HD Demo](https://giant.gfycat.com/NippyAchingAfricanelephant.mp4)

# Requirements (for my setup)
- A Raspberry Pi 4B, running 64 bit Raspbian OS
  - **Warning: I was unable to get PyMuPDF working on 32 bit Raspbian!**
- 2x monitors, preferably a smaller one for the "plaque" and a larger one for the photo
  - I recommend the [ROADOM Raspberry Pi Touchscreen Monitor 7"](https://www.amazon.com/dp/B07VNX4ZWY) for the plaque
  - I also recommend the [Rii 2.4G Mini Wireless Keyboard with Touchpad](https://www.amazon.com/dp/B00I5SW8MC) for KB+M on the Pi
- Python 3
- A [dropbox app](https://www.dropbox.com/developers/apps)
- If running on Windows, [poppler](https://poppler.freedesktop.org/) is also required
  - [Releases for Windows](https://github.com/oschwartz10612/poppler-windows/releases)

# Setup

The dropbox app's folder structure could look like this:
```
  - images
    - image1.jpeg
    - image2.jpeg
    - image3.png
  - templates
    - template1.pdf
    - template2.pdf
    - template3.pdf
  - jsons
    - subject1.json
    - subject2.json
    - subject3.json
```
The only structure requirement is that there must be a ```jsons``` folder that JSONs will be randomly selected from.

## The Images

The images must have the following EXIF data:
- ```DateTimeOriginal```
- ```Model```
- ```FocalLength```
- ```FNumber```
- ```ExposureTime```
- ```ISOSpeedRatings```

## The Templates

The plaque templates must be PDFs with the following fillable text fields:
- ```Title```
- ```Subtitle```
- ```Date```
- ```Location```
- ```Body```
- ```Exposure```

An example PDF is provided in this repository at ```templates/template-exif.pdf```

## The JSONs

The JSONs must have the following structure:
```
{
	"name": "Northern Cardinal",
	"species": "Cardinalis cardinalis",
	"images": [
		{
			"photo": "/images/DSC_1036.jpg",
			"plaque_template": "/templates/template-exif.pdf",
			"location": "Long Island, NY",
			"name_detail": "m."
		},
		{
			"photo": "/images/DSC_1941.jpg",
			"plaque_template": "/templates/template-exif.pdf",
			"location": "Long Island, NY",
			"name_detail": "f."
		}
	]
}
```

Explanation of the fields:
- ```name```, ```species``` and ```location```: used to fill the PDF fields ```Title```, ```Subtitle``` and ```Location``` respectively
- ```name_detail```: If non-empty, then the PDF field ```Title``` is filled in as ```[name] ([name_detail])```. For example ```Cardinal (m.)```
- ```plaque_template```: The path, relative to the dropbox app's base directory, to the PDF template that will be filled & displayed on the plaque monitor
- ```photo```: The path, relative the dropbox app's base directory, to the image that will be displayed on the photo monitor

On each iteration of the gallery, a random JSON is chosen. From that JSON, one object from its ```images``` array is chosen to display.

## Environment Variables

The following environment variables **must be set** for the script to work:

- ```PIGALLERY_APP_KEY```: The key for your Dropbox app.
- ```PIGALLERY_REFRESH_TOKEN```: The refresh token for accessing your Dropbox app. The function ```dropbox_get_refresh_token``` in the script can be used to get a refresh token if ```PIGALLERY_APP_KEY``` is set.

# Installation

- ```pip install -r requirements.txt```

# Usage

- ```python PiGallery.py```

When the script is run, fullscreen Tkinter windows will open on both the plaque & photo monitors.

To exit the script, focus one of the Tkinter windows (I do this by hitting the Windows key and then clicking into the window) and hit the escape key. When the script exits, it will print metrics on how many photos were chosen, broken down by both subject & individual image.

![image](https://user-images.githubusercontent.com/14168201/179371194-e36b2646-07dc-46e1-a204-5ef1776c4533.png)


## CLI Arguments

| Argument              | Meaning | Example Value |
| --------------------- | ------- | ------------- |
| SUBJECT_BUFFER_LENGTH | How many iterations before a subject JSON can be chosen again. Eg. if SUBJECT_BUFFER_LENGTH=10, then ```subject1.json``` can only be selected once every 10 iterations.  | ```10``` |
| PHOTO_BUFFER_LENGTH   | How many iterations before a specific ```image``` within a subject JSON can be chosen again.  | ```50```
| IMAGE_SWAP_RATE_MS    | How long a photo is displayed before the next is chosen, in milliseconds. Note that the Tkinter loop only runs every 500ms, so 500 is functionally the minimum value. | ```60000``` |
| PHOTO_MONITOR_INDEX   | Index of the monitor that will display the photo.  | ```0``` |
| PLAQUE_MONITOR_INDEX  | Index of the monitor that will display the plaque. | ```1``` |
| FADE_IMAGES           | Boolean for determining whether to fade out & in between images. Does not work very well. | ```False``` |
| MAX_RETRIES           | Max amount of attempts for getting a file from the Dropbox app. | ```10``` |
| POPPLER_PATH          | **Required only for Windows.** Path to the Poppler binary folder, used by PyMuPDF to fill the plaque PDF. | ```../../poppler-22.01.0/Library/bin``` |

Example: 

```py PiGallery.py --IMAGE_SWAP_RATE_MS=60000 --PHOTO_BUFFER_LENGTH=50 --POPPLER_PATH=../../poppler-22.01.0/Library/bin --PLAQUE_MONITOR_INDEX=1 --PHOTO_MONITOR_INDEX=0```
