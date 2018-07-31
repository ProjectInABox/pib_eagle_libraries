''' 
A terribly written script that scrapes Digikey for metadata and upates the
current libraries with up-to-date metadata. This particular script scrapes
the following elements from digikey:
DIST        DISTPN        MFR       MPN       PRICE

Make sure that you install the following python packages before using this:
  -> tqdm
  -> BeautifulSoup
  -> requests

In order to use this script, call it as follows:
  ./MetadataUpdater.py  (-f) PATH/TO/DIRECTORY[FILE if -f]

Ensure that your EAGLE libraries contain some sort of link identifier that
looks as follows:
                    [SPECIFIER_]DISTLINK[_SPECIFIER]
where obviously the specifier could be on either side. It will generate
attributes that look similar as follows
                    [SPECIFIER_]ATTRIBUTE[_SPECIFIER]

This script pings Digikey quite often. It it looks stuck, it probably isn't.
The issue is that Digikey is sending back a "403" due to repeated requests.
Placing a delay only worsened the execution time; so, hammering their servers
it is!

- Kenmei
'''

import bs4 as soup
import requests
from os.path import isdir, abspath, join, basename
from os import walk, listdir
from sys import stderr as errStream
from sys import stdout as outStream
import argparse
import re
from tqdm import tqdm
from time import sleep

# Retreives a dictionary with desired values from digikey
MAX_ATTEMPTS = 300000   # like 10 minutes??
error_evaluated = False
def getProductDict(urlSource: str) -> dict:
  prodDetails = None
  attempts = 0
  while(prodDetails == None):
    page = requests.get(urlSource)
    parsed = soup.BeautifulSoup(page.content, 'lxml')

    if(attempts%10 == 0):
      if(parsed.find('div', id='productIndexList') != None):
        raise LinkSearchException()

    if(attempts == MAX_ATTEMPTS):
      raise LinkInvalidException()

   # get desired elements
    prodDetails = parsed.find('table', id="product-details")
    attempts = attempts + 1
  DIST = "Digikey"
  DISTPN = str(prodDetails.find(itemprop='productID').get("content")).lstrip('sku:')
  MFR = prodDetails.find('h2', itemprop='manufacturer').find(itemprop='name').string
  MPN = prodDetails.find('h1', itemprop='model').string.strip()
  
  try:
    prodPricing = parsed.find('table', id="product-dollars")
    for row in prodPricing.find_all('tr'):
      cols = row.find_all('td')
      if(len(cols) == 3 and cols[0].string == '1'):
        UNIT_PRICE = cols[2].string
  except:
    UNIT_PRICE = 'N/A'

  return {'DIST':DIST, 'DISTPN':DISTPN, 'MFR':MFR, 'MPN':MPN, 'PRICE': UNIT_PRICE}

# Given an input directory, return a list of files to be modified
def globEagleLibraries(fileDir: str) -> list:
  if(not isdir(abspath(fileDir))):
    print("\x1b[2K\rInvalid value [{}] passed as directory! Verify that the passed argument"
          " is a valid directory that exists.".format(abspath(fileDir)),
          file=errStream)
    raise ValueError

  toChange = []
  for file in listdir(abspath(fileDir)):
    if(file.endswith('.lbr')):
      toChange += [join(abspath(fileDir), file)]
  return toChange

# Given a single file, parse the XML and appropriately add/update metadata
def updateMetadata(filename: str) -> None:
  with open(filename, 'r') as inputFile:
    if(verbose):
      print('\x1b[2K\rOpening {} for writing'.format(filename), end='')
    xmlDocu = inputFile.read()
    parsed = soup.BeautifulSoup(xmlDocu, 'xml')

  # Now begin parsing file, making sure that the file is actually an
  # EAGLE file that's parsable
  if(parsed.find('eagle') == None):
    print("\r{} is not a valid EAGLE library! Modifications will not be made to it..."
            .format(filename), file=errStream)
    return
  else:
    for device in tqdm(parsed.find_all('device', attrs={'package':re.compile('.*')}), ascii=True, desc='Device'):
      # evaluate changes for each link if possible
      # names will contain suffixes like ['', '_CRIMP', '_CONNECTOR', etc.]
      distlinkList = device.technologies.technology.find_all(attrs={'name': re.compile(r'DISTLINK_*\S*')})
      distlinkNames = [elem.attrs['name'].strip('DISTLINK') for elem in distlinkList]
      distlinkLoc = ['right' if elem=='' or elem[0]=='_' else 'left' for elem in distlinkNames]

      # remove tags that will be updated
      REMOVEMATCH = re.compile('((?!.*LINK)(DIST.*|MFR.*|MPN.*))')
      [toRemove.extract() for toRemove in device.technologies.technology.find_all(attrs={'name': REMOVEMATCH})]

      if(distlinkList == []):
        continue
      if(verbose):
        print('\x1b[2K\r\tUpdating device {} [{}]...'.format(device.attrs['name'], len(distlinkList)), end='')

      errorLog = open("log.txt", "a")      
      for ind, linkToCheck in enumerate(tqdm(distlinkList, ascii=True, desc='Link')):
        curLink = linkToCheck['value']
        if('digikey' in curLink):
          try:
            parsedData = getProductDict(curLink)
          except LinkInvalidException:
            error = ("Invalid Device Link: {} -> {} -> {}...".format(basename(filename)
                        .rstrip('.lbr'), device.parent.parent.attrs["name"],
                        device.attrs["name"]))
            errorLog.write(error+'\n')
            print('\033[93m' + "\x1b[2K\r\t" + error + '\033[0m')
            continue
          except LinkSearchException:
            error = ("Link Leads to Search: {} -> {} -> {}...".format(basename(filename)
                        .rstrip('.lbr'), device.parent.parent.attrs["name"],
                        device.attrs["name"]))
            errorLog.write(error+'\n')
            print('\033[93m' + "\x1b[2K\r\t" + error + '\033[0m')
            continue

          # warn if product is no longer in stock
          if parsedData["PRICE"] == 'N/A':
            error = ("Device is Sold Out: {} -> {} -> {}...".format(basename(filename)
                        .rstrip('.lbr'), device.parent.parent.attrs["name"],
                        device.attrs["name"]))
            errorLog.write(error+'\n')
            print('\033[93m' + "\x1b[2K\r\t" + error + '\033[0m')
            pass

          # Attempt to change data
          tagsToAdd = [soup.Tag(name="attribute", attrs={'constant':'no',
                        'name':(attrStart+distlinkNames[ind] if distlinkLoc[ind]=='right'
                                else distlinkNames[ind]+attrStart), 
                        'value':parsedData[attrStart]}) 
                        for attrStart in parsedData.keys()]
          [distlinkList[-1].insert_after(tags) for tags in tagsToAdd]
        else:
          # print('\r\t{}'.format(curLink))
          continue
      errorLog.close()

  # Write to file (and remove extraneous tags)
  ATTRCLOSEMATCH = re.compile('</attribute>')
  with open(filename, 'w') as inputFile:
    unremovedTags = parsed.prettify().splitlines()
    unremovedIter = unremovedTags.__iter__()
    removedTags = [line.rstrip('>')+'/>' if ATTRCLOSEMATCH.search(nextLine)
                      else line
                      for (line, nextLine) in pairwise(unremovedIter)
                      if not ATTRCLOSEMATCH.search(line)] + ['</eagle>']
    inputFile.write('\n'.join(removedTags))

def pairwise(iterable):
  from itertools import tee

  "s -> (s0,s1), (s1,s2), (s2, s3), ..."
  a, b = tee(iterable)
  next(b, None)
  return zip(a, b)

class LinkSearchException(Exception):
  pass

class LinkInvalidException(Exception):
  pass

# Sets up the argument parser and info for CLI
def evalParser() -> list:
  parser = argparse.ArgumentParser(description='Updates metadata of EAGLE '
                        'libraries within a directory or updates a single file.')
  parser.add_argument('inFile', metavar='FILE', type=str, nargs=1, 
                        help="Input directory [or file] to scan for EAGLE libraries")
  parser.add_argument('-f', '--file', dest='fileFlag', action='store_true', 
                        help="Input file points to a single EAGLE library")
  parser.add_argument('-v', '--verbose', dest='verbose', action='store_true',
                        help='Turns on verbose output for debugging purposes.'
                              ' Note that this also breaks visuals.')
  args = parser.parse_args()
  
  # Used for debugging in script
  global verbose
  verbose = args.verbose
  
  return (args.inFile, args.fileFlag)

# Get the DISTPN, MPN, MFR, PRICE, DIST = DIGIKEY
if __name__ == '__main__':
  receivedFile = evalParser()
  if(receivedFile[1] == True):
    # received input is a file, pass immediately to function
    updateMetadata(receivedFile[0][0])
  else:
    # received input is a directory, parse libraries within and then parse
    # each file individually
    files = globEagleLibraries(receivedFile[0][0])
    for toUpdate in tqdm(files, ascii=True, desc='File'):
      updateMetadata(toUpdate)
    print('\n\n\nFinished')
    if error_evaluated:
      print('\t Check log.txt for warnings')