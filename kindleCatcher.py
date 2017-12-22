import bottlenose
from bs4 import BeautifulSoup
import urllib2
import time
import re
import pickle
import json
import sys
from pprint import pprint
import amazonBookBuyer
import os
import smtplib
import datetime
import sys

FROM_EMAIL = os.environ['KC_FROM_EMAIL']
TO_EMAIL = os.environ['KC_TO_EMAIL']
EMAIL_PASSWORD = os.environ['KC_EMAIL_PASSWORD']
AWS_ACCESS_KEY_ID = os.environ['KC_AWS_ACCESS_KEY_ID']
AWS_SECRET_ACCESS_KEY = os.environ['KC_AWS_SECRET_ACCESS_KEY']
AWS_ASSOCIATE_TAG = os.environ['KC_AWS_ASSOCIATE_TAG']
GOODREADS_KEY = os.environ['KC_GOODREADS_KEY']

def loadSetFromFile(filename): 
	data = None
	with open(filename, 'r') as file:
		data = set(filter(None, file.read().lower().split("\n")))
	file.close()
	return data

def loadListFromFile(filename): 
	data = None
	with open(filename, 'r') as file:
		data = filter(None, file.read().lower().split("\n"))
	file.close()
	return data

BOOKS_SEEN = loadSetFromFile('kindle_seenBooks.dat')
SERIES_OWN = loadSetFromFile('kindle_ownedSeries.dat')
DONTBUY_CATEGORIES = loadSetFromFile('kindle_dontBuyCategories.dat')
DONTBUY_WORDS = loadSetFromFile('kindle_dontBuyWords.dat')
BLOCK_CATEGORIES = loadSetFromFile('kindle_blockCategories.dat')
BLOCK_WORDS = loadSetFromFile('kindle_blockWords.dat')
IGNORE_PARENTHETICALS = loadSetFromFile('kindle_ignoreParentheticals.dat')
CATEGORY_NODES = loadListFromFile('kindle_categories.dat')

def fetchBooks():
	books = {}
	for node in CATEGORY_NODES:
		print node
		fetchNode(books, node)

	buyBooks(books)
	sendEmail(books)
	writeData('kindle_seenBooks.dat', BOOKS_SEEN)
	writeData('kindle_ownedSeries.dat', SERIES_OWN)

def fetchNode(books, node):
	page = 1
	totalPages = 1
	while page <= totalPages:
		items = fetchItems(node, page)
		books.update(parseBookItems(items))
		page += 1

		if items and items.totalpages:
			totalPages = int(items.totalpages.string)
			if totalPages > 10:
				totalPages = 10

		print "  ",len(books)
		items = None

def fetchItems(node, page):
	items = []
	try:
		amazon = bottlenose.Amazon(AWS_ACCESS_KEY_ID, AWS_SECRET_ACCESS_KEY, AWS_ASSOCIATE_TAG, Parser=BeautifulSoup, MaxQPS=1.1)
		response = amazon.ItemSearch(ItemPage=page, BrowseNode=node, SearchIndex="KindleStore", MaximumPrice="0", Sort="salesrank", ResponseGroup="ItemAttributes,EditorialReview,Images,BrowseNodes")
		
		items = response.items
		response.decompose()
	except Exception as e:
		try:
			time.sleep(10)
			response = amazon.ItemSearch(ItemPage=page, BrowseNode=node, SearchIndex="KindleStore", MaximumPrice="0", Sort="salesrank", ResponseGroup="ItemAttributes,EditorialReview,Images,BrowseNodes")
			
			items = response.items
			response.decompose()
		except Exception as e:
			time.sleep(10)
	return items

def parseBookItems(items):
	books = {}
	for item in items:
		asin = None
		if item.asin:
			asin = str(item.asin.string)

		if not asin or asin.lower() in BOOKS_SEEN:
			continue
		if "English" not in str(item.languages):
			continue

		BOOKS_SEEN.add(asin)

		book = {
			"asin": asin,
			"eisbn": None,
			"imageUrl": "",
			"description": "",
			"url": "",
			"own": False,
			"categories": set(),
			"parentCategory": "Misc",
			"title": "",
			"author": "",
			"series": "",
			"ownSeries": False,
			"isbn": "",
			"reviewCount": None,
			"reviewAverage": None,
			"donotbuy": "",
			"boughtStr": "",
			"emailMessage": ""
		}

		if not setCategories(book, item.browsenodes):
				continue

		if item.mediumimage:
			book["imageUrl"] = str(item.mediumimage.url.string)

		if item.detailpageurl:
			book["url"] = str(urllib2.unquote(item.detailpageurl.string))

		fullDescription = ""
		if item.itemattributes:
			book["title"] = str(item.itemattributes.title.string)
			fullDescription += book["title"].lower()

			if "sampler" in book["title"].lower():
				continue

			if item.itemattributes.author:
				book["author"] = str(item.itemattributes.author.string)

		if item.editorialreviews and item.editorialreviews.editorialreview:
			book["description"] = str(item.editorialreviews.editorialreview.content.string)
			book["description"] = re.sub(r'<h[0-9]>|<font.*?>|<big>|<center>', '', book["description"])
			fullDescription += " " + book["description"].lower()
			book["description"] = book["description"][:600]

		skip = False
		for word in BLOCK_WORDS:
			if re.search(r'\b' + word + r'\b', fullDescription):
				skip = True
				break
		if skip:
			continue

		for word in DONTBUY_WORDS:
			if re.search(r'\b' + word + r'\b', fullDescription):
				book["donotbuy"] = "(" + word + ") "
				break
		
		setSeries(book)

		if item.eisbn:
		    books[str(item.eisbn.string)] = book
		else:
		    books[str(item.asin.string)] = book

	return books

def setCategories(book, browsenodes):
	if not browsenodes:
		return False

	allCategories = set()
	for browseNode in browsenodes:
		category = str(browseNode.find('name').string)
		book["categories"].add(category)

		categories = getParentCategories(browseNode.ancestors)
		categories.add(category.lower())

		allCategories.update(categories)
		if set(categories).intersection(BLOCK_CATEGORIES):
			skip = True
			break
		elif set(categories).intersection(DONTBUY_CATEGORIES):
			book["donotbuy"] = "(" + next(iter(set(categories).intersection(DONTBUY_CATEGORIES))) + ") "

		allCategoriesStr = " ".join(allCategories)
		if "nonfiction" in allCategoriesStr:
			book["parentCategory"] = "Nonfiction"
		elif "teen" in allCategoriesStr:
			book["parentCategory"] = "Young Adult"
		elif "children" in allCategoriesStr and "mothers & children" not in allCategoriesStr:
			book["parentCategory"] = "Children"
		elif "christian" in allCategoriesStr:
			book["parentCategory"] = "Christian"
		elif "horror" in allCategoriesStr:
			book["parentCategory"] = "Horror"
		elif "comics" in allCategoriesStr:
			book["parentCategory"] = "Comics"
		elif "romance" in allCategoriesStr:
			book["parentCategory"] = "Romance"
		elif "science fiction" in allCategoriesStr:
			book["parentCategory"] = "Science Fiction"
		elif "classics" in allCategoriesStr:
			book["parentCategory"] = "Classics"
		elif "mystery" in allCategoriesStr:
			book["parentCategory"] = "Fiction"
		elif "fiction" in allCategoriesStr:
			book["parentCategory"] = "Fiction"
		else:
			book["parentCategory"] = "Misc"

def getParentCategories(node):
	parents = set()
	if node and node.browsenode:
		name = node.browsenode.find('name').string

		if name not in ["Subjects", "Kindle eBooks", "Kindle Short Reads", "Kindle Nonfiction Singles", "Kindle Singles"]:
			parents = getParentCategories(node.browsenode.ancestors)
			parents.add(str(name.lower()))
	return parents

def setSeries(book):
	title = book["title"].encode("ascii","ignore").lower()
	title = re.sub(r'short\Wstory|with? free audiobook|\(classic stor.*?\)|\(part .*?\)|story$', '', title).strip()
	for series in IGNORE_PARENTHETICALS:
		title = re.sub(r'\(' + series + r'\)', '', title)
	title = title.strip()

	series = ""
	for match in re.finditer(r'\((.+?)\)', title):
		omatch = match.group(1)
		if re.search(r"(?:the )?box(?:ed)? ?set|edition|kindle single|classic", omatch):
			continue
		match = re.sub(r'book(?: (?:#?[0-9]+|x{0,3}|ix|iv|v?i{0,3}|one|two|three|four|five|six|seven|eight|nine|ten)(?: (?:of|in)(?: the)?)?)?|[^a-z ]|(?:sequel|prequel) to ', '', omatch).strip()

		if re.search(r"\b(?:mini)?series\b", match):
			series = match
			break
		elif series and "book" in omatch:
			series = match
		elif not series:
			series = match

	if not series or "series" not in series:
		title = re.sub(r'\(.*?\)', '', title)
		for side in title.split(":"):
			match = re.search(r"(.+)?book(?: (?:#?[0-9]+|xi{0,3}|ix|iv|v?i{0,3}|one|two|three|four|five|six|seven|eight|nine|ten)(?: (?:of|in)(?: the)?)?)?(.+)?", side)
			if match:
				if (match.group(1) and not match.group(2)) or (match.group(1) and len(match.group(1)) > len(match.group(2))):
					matchGroup = 1
				else:
					matchGroup = 2
				series = match.group(matchGroup)
				break

			if re.search(r"\b(?:mini)?series\b", side):
				if not (series and re.search(r"^ ?a ", side)):
					series = side
					break

	series = re.sub(r'\b(?:mini-?)?series\b', '', series)
	book["series"] = re.sub(r'\s+', ' ', series).strip()

	if series in SERIES_OWN:
		book["ownSeries"] = True

def isWorthBuying(ratingCount, avgRating):
	ratingCount = float(ratingCount)
	if ratingCount < 100:
		return False
	elif ratingCount < 450:
		# books with only 50 ratings need a 4.5, books with 450 need a 3.3
		threshold = 4.65 - 0.003 * ratingCount
	elif ratingCount < 10000:
		threshold = 3.3
	else:
		threshold = 2.5

	return float(avgRating) > threshold

def buyBook(book):
	if (book["ownSeries"] or not book["donotbuy"]) and book["url"]:
		time.sleep(0.5)
		book = amazonBookBuyer.buyBook(book, BLOCK_WORDS, DONTBUY_WORDS)

		if book["boughtStr"] is None:
			return ""

		if ("[BOUGHT]" in book["boughtStr"] or "[OWN]" in book["boughtStr"]) and book["series"]:
			SERIES_OWN.add(book["series"])

	descSoup = BeautifulSoup(book["description"][:600])
	desc = descSoup.prettify()
	descSoup.decompose()
	series = ""
	if book["series"]:
		series = ". Series: " + book["series"]
	message = "<img height=150 hspace=10 vspace=10 align=left src=\""+book["imageUrl"]+"\"> "
	message += book["donotbuy"] + "<b>"+book["boughtStr"]+"<a href="+book["url"]+">"+book["title"]+'</a></b> - <b>'
	message += book["reviewAverage"]+"</b>/"+book["reviewCount"]+" reviews. "
	message += ", ".join(book["categories"]) +".<br>"+desc+"</em></b></i></font> "+series+"<br><BR CLEAR=LEFT> \n"

	return message


def writeData(filename, data):
	with open(filename, 'w') as file:
		file.write("\n".join(data))
	file.close()

def buyBooks(books):
	eisbns = [k for k,v in books.iteritems() if v["eisbn"]]
	eisbns = buyEISBNs(books, eisbns)
	asins = [k for k,v in books.iteritems() if v["asin"]]

	for eisbn in eisbns:
		asin = books[eisbn]["asin"]
		books[asin] = books[eisbn]
		books[eisbn] = None
		asins.add(asin)

	buyASINs(books, asins)

def buyEISBNs(books, eisbns):
	eisbnsList = list(eisbns)
	for i in xrange(0, len(eisbnsList), 999):
		try:
			eisbnChunk = eisbnsList[i:i+999]
			url = "https://www.goodreads.com/book/review_counts.json?key=" + GOODREADS_KEY + "&isbns=" + ",".join(eisbnChunk)
			ratingResults = json.loads(urllib2.urlopen(url).read())
			for book in ratingResults["books"]:
				if book["isbn13"] in books:
					abook = books[book["isbn13"]]

					abook["reviewCount"] = str(book["work_ratings_count"])
					abook["reviewAverage"] = str(book["average_rating"])
					if abook["ownSeries"] or isWorthBuying(book["work_ratings_count"], book["average_rating"]):
						abook["emailMessage"] = buyBook(abook)

					eisbns.remove(book["isbn13"])
				time.sleep(1)
		except urllib2.HTTPError:
			pass
	return eisbns

def buyASINs(books, asins):
	for asin in asins:
		abook = books[asin]
		response = BeautifulSoup(urllib2.urlopen("https://www.goodreads.com/search/index.xml?key=" + GOODREADS_KEY + "&q="+ asin).read())
		ratingCount = response.goodreadsresponse.ratings_count
		avgRating = response.goodreadsresponse.average_rating
		response.decompose()

		if avgRating:
			abook["reviewAverage"] = str(avgRating.string)		
			if ratingCount:
				abook["reviewCount"] = str(ratingCount.string)

				if isWorthBuying(abook["reviewCount"], abook["reviewAverage"]):
					abook["emailMessage"] = buyBook(abook)
					time.sleep(1)
					continue

		if abook["ownSeries"]:
			abook["emailMessage"] = buyBook(abook)

		time.sleep(1)

def sendEmail(books):
	emailMessage = ""
	emailedBooks = set()
	for category in [
			"Science Fiction",
			"Christian",
			"Classics",
			"Fiction",
			"Comics",
			"Nonfiction",
			"Horror",
			"Children",
			"Young Adult",
			"Romance",
			"Misc"
		]:

		filteredBooks = [v for k,v in books.iteritems() if category in v["parentCategory"]]
		if filteredBooks and len(filteredBooks) > 0:
			emailMessage += "<hr><h2>" + category + "</h2>"
			for book in filteredBooks:
				if book["asin"] not in emailedBooks:
					emailMessage += book["emailMessage"]
					emailedBooks.add(book["asin"])

	if emailMessage:
		emailMessage = "From: " + FROM_EMAIL + """
To: """ + TO_EMAIL + """
MIME-Version: 1.0
Content-type: text/html
Subject: Free Kindle Books """ + str(datetime.date.today()) + """

""" + emailMessage

		emailMessage = emailMessage.encode("ascii", "ignore")
		server = smtplib.SMTP('smtp.gmail.com:587')
		server.starttls()
		server.login(FROM_EMAIL, EMAIL_PASSWORD)
		server.sendmail(FROM_EMAIL, TO_EMAIL, emailMessage)

def testSeriesFindingRegex():
	titles = {
		"Love Beyond Time (A Scottish Time Travel Romance): Book 1 (Morna's Legacy Series)": "mornas legacy",
		"Highland Fire (Guardians of the Stone Book 1)": "guardians of the stone",
		"Clean Historical Romance: Western Romance: Uncivil Discord (Inspirational Western Second Chance Rancher Romance) (Westerns Sweet Historical Holiday Frontier Short Stories Book 1)": "westerns sweet historical holiday frontier short stories",
		"Gone (Parallel Trilogy, Book 1) (YA Dystopian)": "parallel trilogy",
		"White Fang  (Wisehouse Classics - with original illustrations)": "",
		"The Lamp of Darkness: The Age of Prophecy Book 1": "the age of prophecy",
		"Sound of Snowfall: A Ghost Bird Series Winter Short Story": "a ghost bird winter",
		"The New Earth: Book 1 In The Moon Penitentiary Series": "moon penitentiary",
		"Rune Gate: Rune Gate Cycle Book 1": "rune gate cycle",
		"Elevated: A YA Sci-Fi Fantasy Superhero Series (Elevated Book #1)": "elevated",
		"Crossed: (prequel to the Crossed Series)": "the crossed",
		"Soulene: A Healer's Tale: Book I of the Soulene Trilogy": "soulene trilogy"
	}

	for title, series in titles.iteritems():
		book = {
			"title": title,
			"asin": 1,
			"series": None
		}
		setSeries(book)

		if series != book["series"]:
			print
			print "Error: Expected \"" + str(book["series"]) + "\" to be \"" + str(series) + "\""
			sys.exit(-1)

if __name__ == "__main__":
	reload(sys)
	sys.setdefaultencoding('utf-8')
	fetchBooks()
