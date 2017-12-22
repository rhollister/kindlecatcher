#i
import re
import email, getpass, imaplib, os, smtplib
import urllib, urllib2
import mechanize
import cookielib
import datetime
import time
import os
from bs4 import BeautifulSoup as Soup
from soupselect import select
import sys

def buyBook(book, blockWords, dontBuyWords, debug=False):
	try:
		storePage = getStorePage(book["url"])

		if hasStopWords(storePage["page"], blockWords) or notAvailable(storePage["page"]):
			book["boughtStr"] = None
			storePage["page"].decompose()
			return book

		hasStopWord = hasStopWords(storePage["page"], dontBuyWords)
		if hasStopWord and not book["ownSeries"]:
			book["donotbuy"] = "[" + hasStopWord + "] "
		elif select(storePage["page"], '#ebooksInstantOrderUpdate'):
			book["boughtStr"]="<font color=FF6600>[OWN]</font> "
		else:
			priceElement = getPriceElement(storePage["page"])
			if priceElement:
				book["boughtStr"] = buy(priceElement, storePage, debug)
			else:
				book["boughtStr"] = "<font color=339933>[FREE?]</font> "

	except Exception as e:
		book["boughtStr"] = "<font color=CC0000>[ERROR BUYING] </font>"

	storePage["page"].decompose()
	return book

def getStorePage(url):
	storePage = None
	try:
		storePage = fetchStorePage(url)
	except:
		time.sleep(5)
		try:
			storePage = fetchStorePage(url)
		except Exception as e:
			print "Error parsing store page"
			print storePage
			raise e
	return storePage

def fetchStorePage(url):	
	cj = getCookieJar()
	br = getBrowser(cj)
	response = br.open(url)
	cj.save()
	storePage = {
		"page": Soup(response.get_data().decode('utf-8',"ignore")),
		"browser": br
	}
	response.decompose()
	return storePage

def getBrowser(cj):
	br = mechanize.Browser()
	br.set_handle_equiv(True)
	br.set_handle_redirect(True)
	br.set_handle_referer(True)
	br.set_handle_robots(False)
	br.addheaders = [('User-agent', 'Mozilla/5.0 (Windows NT 6.1; WOW64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/30.0.1599.69 Safari/537.36')]

	br.set_cookiejar(cj)
	return br

def getCookieJar():
		cj = cookielib.MozillaCookieJar(os.environ['HOME'] + "/cookies.txt")
	cj.load(ignore_expires=True)
	return cj

def getPriceElement(storePage):
	priceElement = select(storePage, 'td.a-color-price')
	if priceElement and len(priceElement) > 0:
		return priceElement

	priceElement = select(storePage, 'span.a-color-price')
	if priceElement and len(priceElement) > 0:
		return priceElement

	return None

def notAvailable(storePage):
	buyElement = select(storePage, '.no-kindle-offer-message')
	if not buyElement or len(buyElement) < 1:
		return False
	return "not currently available" in ''.join(buyElement[0].find(text=True))

def hasStopWords(storePage, stopWords):
	reviews = ""
	reviewElement = select(storePage, '#productDescription')
	if reviewElement:
		reviews = ' '.join(reviewElement[0].findAll(text=True))

	reviewElement = select(storePage, '#reviewsMedley')
	if reviewElement:
		reviews += " " + ' '.join(reviewElement[0].findAll(text=True))

	for word in stopWords:
		if re.search(r'\b' + word + r'\b', reviews):
			return word
	return False

def buy(priceElement, storePage, debug):
	content = ""
	price = priceElement[0].find(text=True).strip()
	if price == "$0.00":
		if debug == False:
			storePage["browser"].select_form(predicate=lambda f: f.attrs.get('id', None) == 'buyOneClick')
			response = storePage["browser"].submit()
			content = response.get_data()
		else:
			content = "will be auto-delivered wirelessly to"
	else:
		 return "<font color=CC0000>[NOT FREE] </font>"
	
	if "Our records show that you already purchased" in content:
		return "<font color=FF6600>[OWN]</font> "

	elif "will be auto-delivered wirelessly to" in content:
		return "<font color=339933>[BOUGHT] </font>"

 	return "<font color=CC0000>[ERROR BUYING] </font>"

if __name__ == "__main__":
	reload(sys)
	sys.setdefaultencoding('utf-8')
