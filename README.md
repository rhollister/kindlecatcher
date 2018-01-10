# Kindle Catcher
"Buy" daily free Kindle books based on their Goodreads reviews and filtered by keywords and categories.

## Features include:
1. Automatically "buys" a book only if:
    1. The book is free
    1. The book has great reviews
    1. The book does not contain stopwords in the description or reviews
    1. The book is not included in undesired categories
1. Uses Goodreads reviews, not Amazon reviews for determination of quality
1. Ignores books seen previously
1. Tries to determine the book series and will purchase sequels in the series if they appear
   1. E.g. If book one of a trilogy is great and purchased, it will buy any sequels even if the reviews aren't as great.
1. Emails a summary of books bought and books containing soft-stopwords

## Getting started
### 1. Environment variables
Email settings (if sending from Gmail, enable IMAP in Gmail Settings)
```bash
KC_EMAIL_FROM='emailtosendfrom@gmail.com'
KC_EMAIL_PASSWORD='fromemailpassword'
KC_EMAIL_TO='emailtosendto@gmail.com'
```
Amazon.com account login
```bash
KC_AMAZON_USER_EMAIL='user@email.com'
KC_AMAZON_PASSWORD='mypassword'
```
Amazon API environment variables - Obtain an [Amazon Product Advertising key](http://docs.aws.amazon.com/AWSECommerceService/latest/DG/becomingDev.html)
```bash
KC_AWS_ACCESS_KEY_ID='ACCESSKEY'
KC_AWS_SECRET_ACCESS_KEY='SECRET_ACCESS_KEY'
KC_AWS_ASSOCIATE_TAG='ASSOCIATE_TAG'
```
Goodreads environment variables - Obtain a [Goodreads API key](https://www.goodreads.com/api)
```bash
KC_GOODREADS_KEY='GOODREADS_ACCESS_KEY'
````

### 2. Data Files
`blacklistCategories.dat` -  List of stopwords in categories
1. If a book contains one of these words in its categories or parent categories it will be immediately skipped.

|Examples|
|---|
| Meditation |
| Health, Fitness| 
| Erotica| 

`blacklistWords.dat` - List of stopwords in the description, editorial review, or user reviews
1. If a book contains one of these words in its description, editorial review, or user reviews, it is immediately skipped.
1. The book will not be "bought" nor included in the email digest

|Examples|
|---|
| mature content|
| steamy| 
| sultry| 

`graylistCategories.dat` - List of soft-stopwords in categories
1. If a book contains one of these words in its categories or parent categories, it will not be "bought"
1. The book will not be "bought", but will be included in the email digest
    
|Examples|
|---|
| Entrepreneurship |
| Paranormal| 
| Self-Help| 

`graylistWords.dat` - List of soft-stopwords in the description, editorial review, or user reviews
1. If a book contains one of these words in its description, editorial review, or user reviews, it will not be "bought"
1. The book will be included in the email digest
    
|Examples|
|---|
| bedroom|
| sensual| 

`ignoreParentheticals.dat` - List of words in paranthesis to ignore in book titles when searching for series names
1. E.g. In the title _Animal Farm (Illustrated)_, ignore "illustrated" as a book series
    
|Examples|
|---|
|illustrated|
|children's|
|with footnotes|
|free|
    
`categories.dat` - List of categories to search for free books
1. Must be a list of numbers for their respective Amazon browsenodes
1. [This is a helpful site](http://www.findbrowsenodes.com/us/KindleStore/154606011) for putting this list together
1. Parent categories can be included, but Amazon limits only 100 items to be returned from a specified category 

Script-generated files that should not need to be edited:
1. `seenBooks.dat` - List of ASINs the script has seen and will ignore them if seen again
1. `boughtSeries.dat` - List of series names that have been bought
    1. If the script sees a book in this series again, it will purchase the book despite a low score or stopwords

## Run

`python kindle_catcher.py`