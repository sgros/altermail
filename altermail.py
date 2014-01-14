#!/usr/bin/python

################################################################################
#
# (C) Stjepan Gros <stjepan.gros@gmail.com>
# Version 20140109-001
#
#
# Python that adds speficied attachment to all the files that pass through
# the Zimbra mail server. The script is tested on Zimbra 8 server and might
# or might not work on other servers.
#
# This script expects to be called as the altermime script. Here is an example
# of the command line that is used:
#
# --input=/opt/zimbra/data/amavisd/tmp/amavis-20140109T134714-09937-k3JDlAGB/email-repl.txt --verbose --disclaimer=/opt/zimbra/data/altermime/global-default.txt --disclaimer-html=/opt/zimbra/data/altermime/global-default.html
#
#
# CHANGELOG
#
# 20140109-001
#	Initial version
#
################################################################################

import argparse
import sys
from time import gmtime, strftime
import re

from email.parser import Parser
from email import header
from email.mime.image import MIMEImage
from email.mime.multipart import MIMEMultipart

# From mail addresses that MUST NOT have appended attachment. This list
# has priority, i.e. if mail address is found in this list no attachment
# is added.
#
# Note that not exact strings are searched for, but it is tested if any
# element of SENDER_BLACK_LIST is substring of From header value!
SENDER_BLACK_LIST = []

# From mail addresses that MUST HAVE appended attachment
#
# If there is an element in this list than only those will be have
# attachment added! If empty, then everyone, except those in black list
# will have attachment added.
#
# Note that not exact strings are searched for, but it is tested if any
# element of SENDER_WHITE_LIST is substring of From header value!
SENDER_WHITE_LIST = ['sgros@sistemnet.hr']

# These mails, if found in the To field, will cause the script not to
# add or modify anything.
#
# Note that not exact strings are searched for, but it is tested if any
# element of RECEIVER_BLACK_LIST is substring of From header value!
RECEIVER_BLACK_LIST = []

# Filename MUST CONTAIN VERSION which will not be added to the message
# but with it we can conclude if there is newer image to be added!
#
BASE_IMG_FILENAME = "reklamasistemnet.jpg" # No path is allowed here!!!
IMG_FILENAME = "0000000000.reklamasistemnet.jpg" # No path is allowed here!!!
IMG_PATH = "/opt/zimbra/altermime/bin/"	# Path to the picture! It HAS TO END WITH FORWARD SLASH!!

# If True, no message will be modified. Useful for debugging purposes.
DRY_RUN = False

# For debugging purposes. 0 -> no debugging at all, 3 highest debugging
# level.
DEBUG_LEVEL = 1

# Placehoder string within the attachment (or in general somewhere within
# the mail where image should appear) that will be changed when image is
# attached.
#
# Note that placeholder has to be comment so that it isn't displayed in case
# no image is attached!
IMGPLACEHOLDER = '<!-- IMAGEHEREPLACEHOLDER -->'
IMGLINK = '<br /><img src="cid:' + BASE_IMG_FILENAME + '@sistemnet.hr"><br />'

def debug(level, msg):
	if level <= DEBUG_LEVEL:
		print "{0} LEVEL{1} {2}".format(strftime("%d %b %Y %H:%M:%S +0000", gmtime()), level, msg)

def replaceImageIfNecessary(msgPart):
	"""
	This function checks if the part is an image, and if so, is it
	advertisement. Then, it checks if the image should be changed,
	i.e. there is a newer version.

	It returns a triplet. The first is True if the advertisement was
	found. The second is True if the advertisement was changed, and
	the third is the old message part (if it was not changed, or not
	found) or a new one in case it was changed.
	"""

	if msgPart.get_content_type() != "image/jpeg":
		debug(3, "Not an image part. Skipping check/replace operation.")
		return False, False, msgPart

	debug(4, "Image part found.")

	if not msgPart.has_key('Content-Disposition') or not msgPart.has_key('Content-Disposition'):
		debug(3, "Message part missing either Content-Disposition or Content-Disposition fields, or both.")
		return False, False, msgPart

	if msgPart['Content-ID'] != '<' + BASE_IMG_FILENAME + '@sistemnet.hr>':
		debug(3, "Content-ID doesn't have expected value")
		return False, False, msgPart

	if msgPart['Content-Disposition'] == 'attachment; filename="' + IMG_FILENAME + '"':
		debug(3, "Content-Disposition already has expected value.")
		return True, False, msgPart

	debug(4, "Content-Disposition has unexpected value {}.".format(msgPart['Content-Disposition']))

	debug(3, "Replacing existing image attachment")

	img = MIMEImage(open(IMG_PATH + IMG_FILENAME).read())
	img.add_header('Content-Disposition', 'attachment', filename=IMG_FILENAME)
	img.add_header('Content-ID', '<' + BASE_IMG_FILENAME + '@sistemnet.hr>')

	return True, True, img

def checkSubparts(msgPart):

	msgParts = []
	imgFound = False
	imgChanged = False
	for msg in msgPart.get_payload():

		if msg.is_multipart():
			found, changed, parts = checkSubparts(msg)
			msg.set_payload(parts)
			msgParts.append(msg)
		else:
			found, changed, newImg = replaceImageIfNecessary(msg)
			msgParts.append(newImg)

		if found and not changed:
			return True, False, None

		imgFound |= found
		imgChanged |= changed

	return imgFound, imgChanged, msgParts

def isHTMLWithSignature(msg):
	"""
	Check if the given message part (that must not be multipart) is
	text/html with a signature in it!
	"""
	return msg.get_content_type() == "text/html"

def processMessagePart(parentContentType, msgPart):

	if not isHTMLWithSignature(msgPart):
		return [msgPart]

	msgPart.set_payload(msgPart.get_payload().replace(IMGPLACEHOLDER, IMGLINK))

	img = MIMEImage(open(IMG_PATH + IMG_FILENAME).read())
	img.add_header('Content-Disposition', 'attachment', filename=IMG_FILENAME)
	img.add_header('Content-ID', '<' + BASE_IMG_FILENAME + '@sistemnet.hr>')

	if parentContentType == "multipart/alternative":

		newMultipart = MIMEMultipart('related')
		newMultipart.attach(msgPart)
		newMultipart.attach(img)

		return [newMultipart]

	elif parentContentType == "multipart/related":

		return msgPart, img

	else:
		return [msgPart]


def processMultipartMessage(msgPart):

	newParts = []
	for msg in msgPart.get_payload():

		if msg.is_multipart():
			processMultipartMessage(msg)
			newParts.append(msg)
		else:
			newParts.extend(processMessagePart(msgPart.get_content_type(), msg))

	msgPart.set_payload(newParts)

def processMailFile(fileName):
	# Open mail
	mainMsg = Parser().parse(open(fileName))

	try:
		debug(1, "Processing message with Message-ID {}".format(mainMsg['Message-ID']))
	except ValueError:
		debug(1, "Processing message with unknown Message-ID")

	########################################################################
	# If mail message isn't already multipart, i.e. MIME, message then
	# we don't do anything with it...
	########################################################################
	if not mainMsg.is_multipart():
		debug(2, "Not a multipart message. Skipping.")
		return

	########################################################################
	# Check sender white and black lists
	########################################################################
	white_found = black_found = False
	debug(3, "Check sender white and black lists")
	for v, t in header.decode_header(mainMsg['From']):
		debug(3, v)

		for w in SENDER_WHITE_LIST:
			try:
				if v.index(w) >= 0: white_found = True
				debug(3, "In From header field found sender {} from the white list".format(w))
			except ValueError:
				pass

		for b in SENDER_BLACK_LIST:
			try:
				if v.index(b) >= 0: black_found = True
				debug(3, "In From header field found sender {} from the black list".format(b))
			except ValueError:
				pass

	if black_found:
		debug(2, "Sender in the black list. Stopping.")
		return

	if not white_found and len(SENDER_WHITE_LIST) > 0:
		debug(2, "White list specified without sender of the current message in the list. Stopping.")
		return

	########################################################################
	# Check receiver black lists
	########################################################################
	black_found = False
	toHeader = mainMsg['To']
	for rb in RECEIVER_BLACK_LIST:
		try:
			if toHeader.index(rb) >= 0: black_found = True
			debug(3, "In To header field found receiver {} from the black list".format(rb))
		except ValueError:
			pass

	if black_found:
		debug(2, "Blacklisted receiver found. Stopped further processing.")
		return

	########################################################################
	# Check if attachment is already there. If so, don't
	# do anything with it, only replace it with newer version
	########################################################################
	debug(3, "Checking if attachment already exists")

	found, changed, newPayload = checkSubparts(mainMsg)
	if found:
		if changed:
			mainMsg.set_payload(newPayload)
			open(fileName, 'w').write(mainMsg.as_string())

		return

	########################################################################
	# No attachment so recreate a message
	########################################################################
	debug(3, "No existing attachment version, recreating message to include one")
	processMultipartMessage(mainMsg)

	########################################################################
	# Finally, add the message to the mail, and save new version of the
	# mail message
	########################################################################
	debug(1, "Inserting image into mail message.")
	if not DRY_RUN:
		open(fileName, 'w').write(mainMsg.as_string())

def main():

	parser = argparse.ArgumentParser(description='Embed image into MIME mail messages')
	parser.add_argument('--input', dest="input")
	parser.add_argument('--verbose', action="store_true", dest="verbose")
	parser.add_argument('--disclaimer', dest="disclaimer-txt")
	parser.add_argument('--disclaimer-html', dest="disclaimer-html")

	args = parser.parse_args()

	processMailFile(args.input)

if __name__ == '__main__':
	main()
