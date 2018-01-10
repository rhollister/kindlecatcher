import re
import email, getpass, imaplib, os, smtplib
import urllib, urllib2
import mechanize
import cookielib
import datetime
import time
import os
from bs4 import BeautifulSoup as Soup
import sys

class Session:
	def __init__(self, page, browser, cookieJar):
		self.page = page
		self.browser = browser
		self.cookieJar = cookieJar

def buyBook(book, blockWords, dontBuyWords, isDryrun=False):
	session = None
	try:
		session = getSession(book.url)

		hasBlockWord = hasStopWords(session.page, blockWords)
		if hasBlockWord and "christian" in book.allCategories:
			book.doNotBuy = "(reviews: " + hasBlockWord + ") "
			return book
		elif hasBlockWord or isNotAvailable(session.page):
			book.boughtStr = None
			session.page.decompose()
			return book

		hasDontBuyWord = hasStopWords(session.page, dontBuyWords)
		if hasDontBuyWord and not book.ownSeries:
			book.doNotBuy = "(reviews: " + hasDontBuyWord + ") "
		elif session.page.select('#ebooksInstantOrderUpdate'):
			book.boughtStr="<font color=FF6600>[OWN]</font> "
		else:
			priceElement = getPriceElement(session.page)
			if priceElement:
				book.boughtStr = makePurchase(priceElement, session, isDryrun)
			else:
				book.boughtStr = "<font color=339933>[FREE?]</font> "

	except Exception as e:
		print "Error buying:", e, book.asin
		book.boughtStr = "<font color=CC0000>[ERROR BUYING] </font>"
		raise e
	if session and session.page:
		session.page.decompose()
	return book

def getSession(url):
	session = None
	try:
		session = startSession(url)
	except:
		time.sleep(5)
		try:
			session = startSession(url)
		except Exception as e:
			print "Error parsing store page at url:", url
			print session
			raise e
	return session

def startSession(url):
	cookieJar = getCookieJar()
	browser = getBrowser(cookieJar)
	response = browser.open(url)
	cookieJar.save()

	page = Soup(response.get_data().decode('utf-8',"ignore"), "html5lib")

	session = Session(page, browser, cookieJar)
	
	return session

def getBrowser(cookieJar):
	browser = mechanize.Browser()
	browser.set_cookiejar(cookieJar)
	browser.set_handle_equiv(True)
	browser.set_handle_redirect(True)
	browser.set_handle_referer(True)
	browser.set_handle_robots(False)
	browser.set_handle_gzip(True) 
	browser.addheaders = [('User-agent', 'Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:57.0) Gecko/20100101 Firefox/57.0')]
	browser.addheaders = [('Accept', 'text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8')]
	browser.addheaders = [('Accept-Language', 'en-US,en;q=0.5')]

	return browser

def getCookieJar():
	cookieJar = cookielib.MozillaCookieJar(os.environ['HOME'] + "/cookies.txt")
	cookieJar.load(ignore_expires=True)
	return cookieJar

def getPriceElement(session):
	priceElement = session.select('td.a-color-price')
	if priceElement and len(priceElement) > 0:
		return priceElement

	priceElement = session.select('span.a-color-price')
	if priceElement and len(priceElement) > 0:
		return priceElement

	return None

def isNotAvailable(session):
	buyElement = session.select('.no-kindle-offer-message')
	if not buyElement or len(buyElement) < 1:
		return False
	return "not currently available" in "".join(buyElement[0].find(text=True))

def hasStopWords(session, stopWords):
	reviews = ""
	reviewElement = session.select('#productDescription')
	if reviewElement:
		reviews = " ".join(reviewElement[0].findAll(text=True)).lower()

	reviewElement = session.select('#reviewsMedley')
	if reviewElement:
		reviews += " " + " ".join(reviewElement[0].findAll(text=True)).lower()

	for word in stopWords:
		if re.search(r'\b' + word + r'\b', reviews):
			return word
	return False

def makePurchase(priceElement, session, isDryrun):
	content = ""
	price = priceElement[0].find(text=True).strip()
	if price == "$0.00":
		if not isDryrun: 
			session.browser.select_form(predicate=lambda f: f.attrs.get('id', None) == 'buyOneClick')
			response = session.browser.submit()
			content = response.get_data()

			if "Forgot your password?" in content and "Keep me signed in." in content:
				content = loginToAmazon(session)
			if "Forgot your password?" in content and "Keep me signed in." in content:
				content = loginToAmazon(session)
			if "Forgot your password?" in content and "Keep me signed in." in content:
				content = loginToAmazon(session)
		else: 
			content = "<title>Thank You</title>"
	else:
		 return "<font color=CC0000>[NOT FREE]</font>"
	
	if "Our records show that you already purchased" in content:
		return "<font color=FF6600>[OWN]</font> "

	elif re.search(r"<title[^>]*>Thank You</title>", content):
		return "<font color=339933>[BOUGHT]</font>"

 	return "<font color=CC0000>[ERROR BUYING]</font>"

def loginToAmazon(session):
	print "loginToAmazon"
	session.browser.select_form(name="signIn")
	#session.browser["email"] = os.environ['KC_AMAZON_USER_EMAIL']
	session.browser["password"] = os.environ['KC_AMAZON_PASSWORD']
	session.browser.find_control("rememberMe").items[0].selected=True
	response = session.browser.submit()
	content = response.get_data()
	session.cookieJar.save()

	return content

if __name__ == "__main__":
	reload(sys)
	sys.setdefaultencoding('utf-8')

	book = Book("")
	book.url = "https://www.amazon.com/Island-Doctor-Moreau-H-Wells-ebook/dp/B0719PYC9K?SubscriptionId=AKIAJWHFB4XXTVFMBOLA&tag=hollblog-20&linkCode=xm2&camp=2025&creative=165953&creativeASIN=B0719PYC9K"
	print buyBook(book, [], []).boughtStr
