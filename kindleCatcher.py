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
import argparse
import progressbar
import copy

FROM_EMAIL = os.environ['KC_EMAIL_FROM']
EMAIL_PASSWORD = os.environ['KC_EMAIL_PASSWORD']
TO_EMAIL = os.environ['KC_EMAIL_TO']
AWS_ACCESS_KEY_ID = os.environ['KC_AWS_ACCESS_KEY_ID']
AWS_SECRET_ACCESS_KEY = os.environ['KC_AWS_SECRET_ACCESS_KEY']
AWS_ASSOCIATE_TAG = os.environ['KC_AWS_ASSOCIATE_TAG']
GOODREADS_KEY = os.environ['KC_GOODREADS_KEY']

def loadSetFromFile(filename): 
	data = None
	with open(filename, 'r') as file:
		data = set(filter(None, file.read().lower().splitlines()))
	file.close()
	return data

def loadListFromFile(filename): 
	data = None
	with open(filename, 'r') as file:
		data = filter(None, file.read().lower().splitlines())
	file.close()
	return data

BOOKS_SEEN = loadSetFromFile('data/seenBooks.dat')
SERIES_OWN = loadSetFromFile('data/ownedSeries.dat')
DONTBUY_CATEGORIES = loadSetFromFile('data/dontBuyCategories.dat')
DONT_BUY_WORDS = loadSetFromFile('data/dontBuyWords.dat')
DONT_BUY_WORDS_GOODREADS_CLEAN = [re.sub(r' ', '-', s.lower()) for s in DONT_BUY_WORDS]
WHITELIST_CATEGORIES = loadSetFromFile('data/whitelistCategories.dat')
BLOCK_CATEGORIES = loadSetFromFile('data/blockCategories.dat')
BLOCK_WORDS = loadSetFromFile('data/blockWords.dat')
BLOCK_WORDS_AMAZON_CLEAN = "-" + " -".join([re.sub(r'[^a-z0-9]', '', s.lower()) for s in BLOCK_WORDS])
BLOCK_WORDS_GOODREADS_CLEAN = [re.sub(r' ', '-', s.lower()) for s in BLOCK_WORDS]

IGNORED_PARENTHETICALS = loadSetFromFile('data/ignoredParentheticals.dat')
CATEGORY_NODES = loadListFromFile('data/categories.dat')

def fetchBooks(isDryrun):
	books = {}
	print "Fetching books from categories:"
	bar = progressbar.ProgressBar()

	for node in bar(CATEGORY_NODES):
		fetchCategoryNode(books, node)

	print
	print "Applying quality control to", len(books), "books"
	booksToBuy = removeUnwantedBooks(books)
	booksBought = []

	for book in booksToBuy:
		book.emailMessage = buyBook(book, isDryrun)

		if book.boughtStr:
			booksBought.append(book)
			writeData('data/ownedSeries.dat', SERIES_OWN, isDryrun)

	print
	print "Emailing", len(booksBought), "books"
	sendEmail(booksBought)

	writeData('data/seenBooks.dat', BOOKS_SEEN, isDryrun)

def fetchCategoryNode(books, node):
	page = 1
	totalPages = 1
	while page <= totalPages:
		items = fetchBookItems(node, page)
		books.update(parseBookItems(items))
		page += 1

		if items and items.totalpages:
			totalPages = int(items.totalpages.string)
			if totalPages > 10:
				totalPages = 10

		items = None

def fetchBookItems(node, page):
	items = []
	try:
		amazon = bottlenose.Amazon(AWS_ACCESS_KEY_ID, AWS_SECRET_ACCESS_KEY, AWS_ASSOCIATE_TAG, 
			Parser=lambda text: BeautifulSoup(text, 'html5lib'), MaxQPS=1.1)
		response = amazon.ItemSearch(ItemPage=page, BrowseNode=node, SearchIndex="KindleStore", MaximumPrice="0", 
			Sort="salesrank", ResponseGroup="AlternateVersions,ItemAttributes,EditorialReview,Images,BrowseNodes",
			Keywords=BLOCK_WORDS_AMAZON_CLEAN)
		
		items = copy.copy(response.items)
		response.decompose()
	except Exception as e:
		try:
			print "Error when fetching book items, retrying.", e
			time.sleep(10)
			response = amazon.ItemSearch(ItemPage=page, BrowseNode=node, SearchIndex="KindleStore", MaximumPrice="0", 
				Sort="salesrank", ResponseGroup="AlternateVersions,ItemAttributes,EditorialReview,Images,BrowseNodes",
				Keywords=BLOCK_WORDS_AMAZON_CLEAN)
			
			items = copy.copy(response.items)
			response.decompose()
		except Exception as e:
			print "Error when fetching book items a second time.", e
			print e, node
			time.sleep(10)

	return items

class Book:
	def __init__(self, asin):
		self.asin = asin
		self.eisbn = None
		self.imageUrl = ""
		self.description = ""
		self.pageCount = ""
		self.url = ""
		self.own = False
		self.categories = set()
		self.parentCategory = "Misc"
		self.title = ""
		self.author = ""
		self.year = ""
		self.series = ""
		self.ownSeries = False
		self.reviewCount = ""
		self.reviewAverage = ""
		self.doNotBuy = ""
		self.boughtStr = ""
		self.emailMessage = ""
		self.allCategories = ""
		self.ebookOnly = True
		self.goodreadsId = ""

def parseBookItems(items):
	books = {}
	for item in items:
		asin = None
		if item.asin:
			asin = str(item.asin.string)

		book = Book(asin)

		title = "Not found"
		if item.itemattributes:
			title = str(item.itemattributes.title.string.encode("ascii", "ignore"))

		if not asin or asin.lower() in BOOKS_SEEN:
			if asin:
				logRejects(str(asin), title, "Seen before")
			continue
		if "English" not in str(item.languages):
			logRejects(asin, title, "Not English: " + str(item.languages))
			continue
		if item.numberofpages:
			book.pageCount = int(item.numberofpages.string)
		 	if book.pageCount < 50:
				logRejects(asin, title, "Too short: " + str(item.numberofpages.string))
				continue
		if item.isadultproduct and str(item.isadultproduct.string) != "0":
			logRejects(asin, title, "Adult product: " + str(item.isadultproduct.string))
			continue		
		if "sampler" in title.lower():
			logRejects(asin, title, "sampler")
			continue

		skipBook = False

		if item.alternateversions:
			for alternateversion in item.alternateversions:
				if alternateversion.asin and alternateversion.asin.string.lower() in BOOKS_SEEN:
					skipBook = True
					break
				if alternateversion.binding:
					if "paperback" in alternateversion.binding.string.lower() or "hardback" in alternateversion.binding.string.lower() or "library" in alternateversion.binding.string.lower():
						book.ebookOnly = False

		BOOKS_SEEN.add(asin)

		if skipBook:
			continue

		if item.mediumimage:
			book.imageUrl = str(item.mediumimage.url.string)

		if item.detailpageurl:
			book.url = urllib2.unquote(str(item.detailpageurl.string))

		fullDescription = ""
		if item.itemattributes:
			book.title = str(item.itemattributes.title.string.encode("ascii", "ignore"))
			fullDescription += book.title.lower()

			if item.itemattributes.author:
				book.author = str(item.itemattributes.author.string.encode("ascii", "ignore"))

		if not setCategories(book, item.browsenodes):
			continue

		if item.editorialreviews and item.editorialreviews.editorialreview:
			book.description = str(item.editorialreviews.editorialreview.content.string.encode("ascii", "ignore"))
			book.description = re.sub(r'<h[0-9]>|<font.*?>|<big>|<center>', '', book.description)
			fullDescription += " " + book.description.lower()
			book.description = book.description[:600]

		if "White Listed" not in book.parentCategory:
			skipBook = False
			for word in BLOCK_WORDS:
				if re.search(r'\b' + word + r'\b', fullDescription):
					logRejects(asin, book.title, "contains block word: " + str(word))
					skipBook = True
					break
			if skipBook:
				continue

			for word in DONT_BUY_WORDS:
				if re.search(r'\b' + word + r'\b', fullDescription):
					book.doNotBuy = "(desc: " + word + ") "
					break
		
		setSeries(book)

		if item.eisbn:
			book.eisbn = str(item.eisbn.string)
			books[str(item.eisbn.string)] = book
		if item.isbn:
			book.eisbn = str(item.isbn.string)
			books[str(item.isbn.string)] = book
		else:
		    books[str(item.asin.string)] = book

	return books

def setCategories(book, browseNodes):
	if not browseNodes:
		logRejects(book.asin, book.title, "no browse node")
		return False

	allCategoriesStr = ""
	for browseNode in browseNodes:
		category = str(browseNode.find('name').string.encode("ascii", "ignore"))
		book.categories.add(category)

		categories = getParentCategories(browseNode.ancestors)
		categories.add(category.lower())

		allCategoriesStr += " ".join(categories)

		for whiteListKeyword in WHITELIST_CATEGORIES:
			if whiteListKeyword in allCategoriesStr:
				book.parentCategory = "White Listed"
				return True

		if set(categories).intersection(BLOCK_CATEGORIES):
			logRejects(book.asin, book.title, "block category: " + str(set(categories).intersection(BLOCK_CATEGORIES)))
			return False
		elif set(categories).intersection(DONTBUY_CATEGORIES):
			book.doNotBuy = "(category: " + next(iter(set(categories).intersection(DONTBUY_CATEGORIES))) + ") "

	book.allCategories = allCategoriesStr

	if "nonfiction" in allCategoriesStr:
		book.parentCategory = "Nonfiction"
	elif "teen" in allCategoriesStr:
		book.parentCategory = "Young Adult"
	elif "children" in allCategoriesStr and "mothers & children" not in allCategoriesStr:
		book.parentCategory = "Children"
	elif "christian" in allCategoriesStr:
		book.parentCategory = "Christian"
	elif "horror" in allCategoriesStr:
		book.parentCategory = "Horror"
	elif "comics" in allCategoriesStr:
		book.parentCategory = "Comics"
	elif "romance" in allCategoriesStr:
		book.parentCategory = "Romance"
	elif "science fiction" in allCategoriesStr:
		book.parentCategory = "Science Fiction"
	elif "classics" in allCategoriesStr:
		book.parentCategory = "Classics"
	elif "mystery" in allCategoriesStr:
		book.parentCategory = "Fiction"
	elif "fiction" in allCategoriesStr:
		book.parentCategory = "Fiction"
	else:
		book.parentCategory = "Misc"

	return True

def getParentCategories(node):
	parents = set()
	if node and node.browsenode:
		name = node.browsenode.find('name').string

		if name not in ["Subjects", "Kindle eBooks", "Kindle Short Reads", "Kindle Nonfiction Singles", "Kindle Singles"]:
			parents = getParentCategories(node.browsenode.ancestors)
			parents.add(str(name.lower().encode("ascii", "ignore")))
	return parents

def setSeries(book):
	title = book.title.encode("ascii", "ignore").lower()
	title = re.sub(r'short\Wstory|with? free audiobook|\(classic stor.*?\)|\(part .*?\)|story$', '', title).strip()
	for series in IGNORED_PARENTHETICALS:
		title = re.sub(r'\(' + series + r'\)', '', title)
	title = title.strip()

	series = ""
	for parens in re.finditer(r'\((.+?)\)', title):
		omatch = parens.group(1)
		if re.search(r"(?:the )?box(?:ed)? ?set|edition|kindle single|classic", omatch):
			continue
		parens = re.sub(r'book(?: (?:#?[0-9]+|x{0,3}|ix|iv|v?i{0,3}|one|two|three|four|five|six|seven|eight|nine|ten)(?: (?:of|in)(?: the)?)?)?|[^a-z ]|(?:sequel|prequel) to ', '', omatch).strip()

		if re.search(r"\b(?:mini)?series\b", parens):
			match = re.sub(r'young adult|horror|children|romance|mystery|love|fantasy|(?:mini)?series|\s', '', parens)
			if (len(match) > 0):
				series = parens
				break
		elif series and "book" in omatch:
			series = parens
		elif not series:
			series = parens

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
	series = re.sub(r'^[^a-z0-9]+|[^a-z0-9]+$', '', series)
	series = re.sub(r'\s+', ' ', series).strip()

	if len(series) > 0:
		series += "~~" + book.author.lower()
		book.series = series

	if series in SERIES_OWN:
		book.ownSeries = True

def removeUnwantedBooks(books):
	eisbns = [k for k,v in books.iteritems() if v.eisbn and not v.ownSeries]
	print
	print "  Looking up reviews by EISBN for", len(eisbns), "books"
	unsetEISBNs = removeUnwantedByEISBNLookup(books, eisbns)

	for eisbn in unsetEISBNs:
		asin = books[eisbn].asin
		books[asin] = books[eisbn]
		del books[eisbn]

	asins = [k for k,v in books.iteritems() if (not v.reviewCount and not v.ownSeries)]

	print
	print "  Looking up reviews by ASIN for", len(asins), "books"
	removeUnwantedByASINLookup(books, asins)

	booksToBuy = [v for k,v in books.iteritems() if v.goodreadsId and not v.doNotBuy and not v.ownSeries]
	print
	print "  Filtering by Goodreads info for", len(booksToBuy), "books"
	booksToBuy = removeUnwantedByGoodreadsInfo(booksToBuy)

	return booksToBuy

def removeUnwantedByEISBNLookup(books, eisbns):
	eisbnsList = list(eisbns)
	for i in xrange(0, len(eisbnsList), 999):
		try:
			eisbnChunk = eisbnsList[i:i+999]
			time.sleep(1)
			url = "https://www.goodreads.com/book/review_counts.json?key=" + GOODREADS_KEY + "&isbns=" + ",".join(eisbnChunk)
			ratingResults = json.loads(urllib2.urlopen(url).read())
			for result in ratingResults["books"]:

				book = books[result["isbn13"]]
				if not book:
					book = books[result["isbn"]]

				if book:
					if isWorthBuying(result["work_ratings_count"], result["average_rating"], book):
						book.buyStatus = True
						book.reviewCount = str(result["work_ratings_count"])
						book.reviewAverage = str(result["average_rating"])
						book.goodreadsId = str(result["id"])

					else:
						logRejects(book.asin, book.title, "low reviews: "+str(result["work_ratings_count"])  + ", " + str(result["average_rating"]))
						del books[result["isbn13"]]

					eisbns.remove(result["isbn13"])
		except urllib2.HTTPError:
			pass
	return eisbns

def removeUnwantedByASINLookup(books, keys):
	bar = progressbar.ProgressBar()
	for key in bar(keys):
		book = books[key]
		asin = book.asin
		time.sleep(1)
		try:
			response = BeautifulSoup(urllib2.urlopen("https://www.goodreads.com/search/index.xml?key=" + GOODREADS_KEY + "&q="+ asin).read(), "html5lib")
		except Exception as e:
			time.sleep(10)
			try:
				response = BeautifulSoup(urllib2.urlopen("https://www.goodreads.com/search/index.xml?key=" + GOODREADS_KEY + "&q="+ asin).read(), "html5lib")
			except Exception as e:
				continue

		avgRating = response.goodreadsresponse.average_rating
		ratingCount = response.goodreadsresponse.ratings_count

		buyStatus = False
		book.reviewCount = None
		book.reviewAverage = None
		if avgRating and ratingCount:
			book.reviewAverage = str(avgRating.string)
			book.reviewCount = str(ratingCount.string)
			book.goodreadsId = str(response.goodreadsresponse.best_book.id.string)

			if isWorthBuying(book.reviewCount, book.reviewAverage, book):
				buyStatus = True

		if buyStatus:
			book.buyStatus = True
		else:
			if not book.title:
				book.title = book.asin
			logRejects(asin, book.title, "low reviews: " + str(book.reviewCount) + ", " + str(book.reviewAverage))
			del books[key]

		response.decompose()

def removeUnwantedByGoodreadsInfo(books):
	booksToRemove = []
	bar = progressbar.ProgressBar()
	for book in bar(books):
		time.sleep(1)
		response = BeautifulSoup(urllib2.urlopen("https://www.goodreads.com/book/show.xml?key=" + GOODREADS_KEY + "&id="+ book.goodreadsId).read(), "html5lib")

 		if containsStopWord(str(response.goodreadsresponse.book.description), BLOCK_WORDS):
			booksToRemove.append(book)
			logRejects(book.asin, book.title, "goodreads description: " + containsStopWord(shelf["name"], BLOCK_WORDS))
		else:
			for shelf in response.find_all("shelf"):
				if shelf["count"] == "1" or shelf["count"] == "2":
					break

				if containsStopWord(shelf["name"], BLOCK_WORDS_GOODREADS_CLEAN):
					booksToRemove.append(book)
					logRejects(book.asin, book.title, "blockshelf: " + containsStopWord(shelf["name"], BLOCK_WORDS_GOODREADS_CLEAN))
					break

				stopword = containsStopWord(shelf["name"], DONT_BUY_WORDS_GOODREADS_CLEAN)
				if stopword:
					book.doNotBuy = "(shelf: " + stopword + ") "
					break

		year = response.goodreadsresponse.book.work.original_publication_year
		try: 
			year = int(year)
			if year < 0:
				year = str(abs(year)) + " BC"
			elif year < 1500:
				year = str(year) + " AD"
		except ValueError:
			pass

		book.year = str(year)

		response.decompose()

	return [book for book in books if book not in booksToRemove]

def containsStopWord(string, stopwords):
	if not string:
		return None

	for stopword in stopwords:
		if re.search(r'\b' + stopword + r'\b', string):
			return stopword
	return None

def isWorthBuying(ratingCount, avgRating, book):
	ratingCount = float(ratingCount)

	modifier = 1.0
	if book.pageCount < 160:
		modifier *= 1.5
	if book.ebookOnly:
		modifier *= 2
	if "christian" in book.allCategories:
		modifier /= 2

	if ratingCount < 600 * modifier:
		return False
	elif ratingCount < 1500 * modifier:
		# regular books with only 600 ratings need a 4.5, books with 1500 need a 3.6
		#  short books with only 900 ratings need a 4.5, books with 2250 need a 3.6
		#  ebooks with only 1200 ratings need a 4.5, books with 3000 need a 3.6
		# regular christian books with only 300 ratings need a 4.5, books with 750 need a 3.6
		threshold = 5.1 - 0.001 * ratingCount
	elif ratingCount < 10000 * modifier:
		threshold = 3.6
	else:
		threshold = 3

	return float(avgRating) > threshold

def buyBook(book, isDryrun):
	if (book.ownSeries or not book.doNotBuy) and book.url:
		time.sleep(0.5)
		book = amazonBookBuyer.buyBook(book, BLOCK_WORDS, DONT_BUY_WORDS, isDryrun)

		if book.boughtStr is None:
			return ""

		if ("[BOUGHT]" in book.boughtStr or "[OWN]" in book.boughtStr) and book.series:
			SERIES_OWN.add(book.series)

	return book

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

		filteredBooks = [book for book in books if category in book.parentCategory]
		if filteredBooks and len(filteredBooks) > 0:
			emailMessage += "<hr><h2>" + category + "</h2>"
			for book in filteredBooks:
				descSoup = BeautifulSoup(book.description[:800], "html5lib")
				book.description = descSoup.prettify().encode("ascii", "ignore")
				descSoup.decompose()
				series = ""
				if book.series:
					series = "Series: " + book.series.encode("ascii", "ignore")

				#print ', '.join("%s: %s" % item for item in vars(book).items())

				book.categories = ', '.join(book.categories)

				message = """
<img height=150 hspace=10 vspace=10 align=left src=\"%(imageUrl)s\">
%(doNotBuy)s <b>%(boughtStr)s <a href=%(url)s>%(title)s</a></b> 
<b>%(reviewAverage)s</b>/<a href=https://www.goodreads.com/book/show/%(goodreadsId)s>%(reviewCount)s reviews</a>.
%(categories)s. %(year)s. %(author)s<br>
%(description)s</em></b></i></font><br>
%(series)s<br><BR CLEAR=LEFT> \n
				""" % vars(book)

				if book.asin not in emailedBooks:
					emailMessage += message
					emailedBooks.add(book.asin)

	if emailMessage:
		emailMessage = "From: " + FROM_EMAIL + """
To: """ + TO_EMAIL + """
MIME-Version: 1.0
Content-type: text/html
Subject: """ + str(len(emailedBooks)) + " Free Kindle Books " + str(datetime.date.today()) + """

""" + emailMessage

		emailMessage = emailMessage.encode("ascii", "ignore")
		server = smtplib.SMTP('smtp.gmail.com:587')
		server.starttls()
		server.login(FROM_EMAIL, EMAIL_PASSWORD)
		server.sendmail(FROM_EMAIL, TO_EMAIL, emailMessage)

def writeData(filename, data, isDryrun):
	if isDryrun:
		return

	with open(filename, 'w') as file:
		file.write("\n".join(data))
	file.close()

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
		"Soulene: A Healer's Tale: Book I of the Soulene Trilogy": "soulene trilogy",
		"A Bid For Love: (Deal for Love, Book 1) (Love Series)": "deal for love"
	}

	for title, series in titles.iteritems():
		book = Book(1)
		book.title = title

		setSeries(book)

		if series != book.series:
			print
			print "Test failed: Expected \"" + str(book.series) + "\" to be \"" + str(series) + "\""
			sys.exit(-1)

def logRejects(asin, title, message):
	if not LOG_REJECTS:
		return

	title = str(title)
	message = str(message)
	if re.search("[A-Z]", asin): 
		link = "https://www.amazon.com/dp/"
	else:
		link = "https://www.amazon.com/s?field-keywords="

	if "low review" not in message:
		title = "<b>" + title + "</b>"
		if "Too short" not in message:
			message = "<b>" + message + "</b>"
	html = "<tr><td class=link><a href="+link+asin+">"+asin+"</a></td><td class=reason>"+message+"</td><td class=title>"+title+"</td></tr>"

	with open("rejectedASINS.dat", 'a') as file:
		file.write(asin + "\n")
	file.close()

	with open("rejectedASINS.html", 'a') as file:
		file.write(html + "\n")
	file.close()

class DisplayUsageOnErrorParser(argparse.ArgumentParser):
    def error(self, message):
        sys.stderr.write('error: %s\n' % message)
        self.print_help()
        sys.exit(2)

if __name__ == "__main__":
	reload(sys)
	sys.setdefaultencoding('utf-8')
	
	isDryrun = False
	LOG_REJECTS = False

	parser = DisplayUsageOnErrorParser()
	parser.add_argument('-c', '--cull-owned', help='Create an HTML table of owned books that no longer meet quality critera', action='store_true')
	parser.add_argument('-d', '--dry-run', help='No purchases will be made and no data will be written to disk', action='store_true')
	parser.add_argument('-t', '--test-regex', help='Run regex tests', action='store_true')
	args = parser.parse_args()

	if args.cull_owned:
	 	LOG_REJECTS = True
 		print "Writing rejected books to rejectedASINS.html and rejectedASINS.dat"

	if args.dry_run:
	 	isDryrun = True
	
		if args.cull_owned:
 			print "Running in dry-run mode. No purchases will be made and no data will be written to disk, except culling data."
		else:
	 		print "Running in dry-run mode. No purchases will be made and no data will be written to disk."

	if args.test_regex:
		testSeriesFindingRegex()

		print "All tests passed."
		sys.exit(0)

	print ""
	fetchBooks(isDryrun)