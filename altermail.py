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
# 20140116-001
#       When inserting image reference, take care of encoding used!
#
# 20140116-002
#       Added ability to save messages before and after processing
#	When error occurs dump message into a separate file for a later analysis
#	Use local time instead of gmtime for log messages
#	Introduced functionality to prevent attaching image for internal mail messages
#	Reorganized code for black and white lists
#
################################################################################

import argparse
import sys
from time import localtime, strftime
import re

from email.parser import Parser
from email import header
from email.mime.image import MIMEImage
from email.mime.multipart import MIMEMultipart

# What is my domain? The idea is that messages internal to the domain
# should not be modified!
MY_DOMAIN = "@sistemnet.hr"

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
BASE_IMG_FILENAME = "ponudasistemnet.jpg" # No path is allowed here!!!
IMG_FILENAME = "00ponudasistemnet.jpg" # No path is allowed here!!!
IMG_PATH = "/opt/zimbra/altermime/bin/"	# Path to the picture! It HAS TO END WITH FORWARD SLASH!!

# If True, no message will be modified. Useful for debugging purposes.
DRY_RUN = True

# For debugging purposes. 0 -> no debugging at all, 3 highest debugging
# level.
DEBUG_LEVEL = 4

# Should processed mails be saved for a later analysis?
SAVE_PROCESSED_MAILS = False
SAVE_DIRECTORY = "/tmp/" # It has to end with slash!

# Placehoder string within the attachment (or in general somewhere within
# the mail where image should appear) that will be changed when image is
# attached.
#
# Note that placeholder has to be comment so that it isn't displayed in case
# no image is attached!
IMGPLACEHOLDER = '<!-- IMAGEHEREPLACEHOLDER -->'
IMGLINK = {
	'7bit':			'<br /><img src="cid:' + BASE_IMG_FILENAME + '@sistemnet.hr"><br />\r\n',
	'quoted-printable':	'<br /><img src=3D"cid:' + BASE_IMG_FILENAME + '@sistemnet.hr"><br />\r\n'
}

def debug(level, msg):
	if level <= DEBUG_LEVEL:
		print "{0} LEVEL{1} {2}".format(strftime("%d %b %Y %H:%M:%S", localtime()), level, msg)

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
	if msg.get_content_type() != "text/html":
		return False

	return True

def processMessagePart(parentContentType, msgPart):

	if not isHTMLWithSignature(msgPart):
		return []

	oldHTMLPart = msgPart.get_payload()
	try:
		contentTransferEncoding = msgPart['Content-Transfer-Encoding']
		newHTMLPart = oldHTMLPart.replace(IMGPLACEHOLDER, IMGLINK[contentTransferEncoding])
	except KeyError:
		debug(0, "Unknown Content-Transfer-Encoding value {0}".format(contentTransferEncoding))
		return []

	if oldHTMLPart == newHTMLPart:
		debug(3, "No replace was done in text/html part of the message")
		return []

	msgPart.set_payload(newHTMLPart)

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
	replaced = False
	for msg in msgPart.get_payload():

		if msg.is_multipart():
			replaced |= processMultipartMessage(msg)
			newParts.append(msg)
		else:
			newList = processMessagePart(msgPart.get_content_type(), msg)
			if newList != []:
				replaced = True
				newParts.extend(newList)
			else:
				newParts.append(msg)

	msgPart.set_payload(newParts)

	return replaced

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
	# Create a lists of senders and recepients!
	########################################################################
	fromStr = mainMsg['From']
	debug(4, "FROM string: {0}".format(fromStr))
	fromList = []
	if fromStr:
		fromList = re.findall('<[^ <]+@[^ >,]+>', fromStr)
		if fromList == []:
			fromList = re.findall('[^ <]+@[^ >,]+', fromStr)
	debug(3, "Discovered sender: {0}".format(str(fromList)))

	toStr = mainMsg['To']
	debug(4, "TO string: {0}".format(toStr))
	toList = []
	if toStr:
		toList = re.findall('<[^ <]+@[^ >,]+>', toStr)
		if toList == []:
			toList = re.findall('[^ <]+@[^ >,]+', toStr)

	ccStr = mainMsg['Cc']
	debug(4, "CC string: {0}".format(ccStr))
	ccList = []
	if ccStr:
		ccList = re.findall('<[^ <]+@[^ >,]+>', ccStr)
		if ccList == []:
			ccList = re.findall('[^ <]+@[^ >,]+', ccStr)

	toList.extend(ccList)
	debug(3, "Discovered recipients: {0}".format(str(toList)))

	########################################################################
	# Check if this is an internal mail. If so, don't do anything
	# with a message
	########################################################################
	try:
		for mailAddress in toList:
			mailAddress.index(MY_DOMAIN)

		debug(1, "Internal mail message. Skipping.")

		return

	except ValueError:
		debug(1, "Found external mail address.")

	########################################################################
	# Check blacklisted sender. If there is one, just skip further
	# processing
	########################################################################
	for mailAddress in toList:
		for b in SENDER_BLACK_LIST:
			try:
				mailAddress.index(b)
				debug(3, "In From header field found sender {} from the black list".format(b))

				debug(2, "Sender in the black list. Stopping.")
				return
			except ValueError:
				pass

	########################################################################
	# Check white list
	########################################################################
	if len(SENDER_WHITE_LIST):
		white_found = False
		for mailAddress in toList:

			for w in SENDER_WHITE_LIST:
				try:
					mailAddress.index(w)
					white_found = True

					debug(3, "In From header field found sender {} from the white list".format(w))
					break

				except ValueError:
					pass

			if white_found:
				break

		if not white_found:
			debug(2, "White list specified without sender of the current message in the list. Stopping.")
			return

	########################################################################
	# Check blacklisted receiver. If there is one, just skip further
	# processing
	########################################################################
	for mailAddress in toList:
		for b in RECEIVER_BLACK_LIST:
			try:
				mailAddress.index(b)
				debug(3, "In From header field found receiver {} from the black list".format(b))

				debug(2, "Receiver in the black list. Stopping.")
				return
			except ValueError:
				pass

	########################################################################
	# Check if attachment is already there. If so, don't
	# do anything with it, only replace it with newer version
	########################################################################
	debug(2, "Checking if attachment already exists")

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
	replaced = processMultipartMessage(mainMsg)

	########################################################################
	# Finally, add the message to the mail, and save new version of the
	# mail message
	########################################################################
	if not DRY_RUN:
		if replaced:
			debug(2, "Inserting image into mail message.")
			open(fileName, 'w').write(mainMsg.as_string())
		else:
			debug(3, "Probably old disclaimer without image reference. No image attached!")
	else:
		debug(1, "Dry run specified. Message wasn't changed!")

def main():

	parser = argparse.ArgumentParser(description='Embed image into MIME mail messages')
	parser.add_argument('--input', dest="input")
	parser.add_argument('--verbose', action="store_true", dest="verbose")
	parser.add_argument('--disclaimer', dest="disclaimer-txt")
	parser.add_argument('--disclaimer-html', dest="disclaimer-html")

	args = parser.parse_args()

	try:
		if SAVE_PROCESSED_MAILS:
			baseFileName = strftime("%Y%b%d%H%M%S", localtime())
			open(SAVE_DIRECTORY + baseFileName + ".input.eml", 'w').write(open(args.input).read())

		processMailFile(args.input)

		if SAVE_PROCESSED_MAILS:
			open(SAVE_DIRECTORY + baseFileName + ".output.eml", 'w').write(open(args.input).read())

	except Exception as ex:
		print ex
		baseFileName = strftime("%Y%b%d%H%M%S", localtime())
		open(SAVE_DIRECTORY + baseFileName + ".error.eml", 'w').write(open(args.input).read())

if __name__ == '__main__':
	main()
