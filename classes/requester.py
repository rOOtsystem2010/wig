import requests, queue, threading, time, hashlib,sys, re
from classes.cache import Cache
from classes.results import Results


class RequesterThread(threading.Thread):
	def __init__(self, id, queue, cache, requested):
		threading.Thread.__init__(self)
		self.id = id
		self.queue = queue
		self.cache = cache
		self.requested = requested
		self.kill = False


	def clean_page(self, response):
		# this the same method nmap's http.lua uses for error page detection
		# nselib/http.lua: clean_404
		# remove information from the page that might not be static

		page = response.content
		
		# time
		page = re.sub(b'(\d?\d:?){2,3}', b'',page)
		page = re.sub(b'AM', b'',page, flags=re.IGNORECASE)
		page = re.sub(b'PM', b'',page, flags=re.IGNORECASE)

		# date with 4 digit year
		page = re.sub(b'(\d){8}', '',page)
		page = re.sub(b'\d{4}-\d{2}-\d{2}', b'',page)
		page = re.sub(b'\d{4}/\d{2}/\d{2}', b'',page)
		page = re.sub(b'\d{2}-\d{2}-\d{4}', b'',page)
		page = re.sub(b'\d{2}/\d{2}/\d{4}', b'',page)

		# date with 2 digit year
		page = re.sub( b'(\d){6}', '',page)
		page = re.sub( b'\d{2}-\d{2}-\d{2}', b'',page)
		page = re.sub( b'\d{2}/\d{2}/\d{2}', b'',page)
		
		# links and paths
		page = re.sub( b'/[^ ]+',  b'', page)
		page = re.sub( b'[a-zA-Z]:\\[^ ]+',  b'', page)

		# return the fingerprint of the stripped page 
		return hashlib.md5(page).hexdigest().lower()


	def make_request(self, item):
		host = item['host']
		url = item['url']

		if host.endswith('/') and url.startswith('/'):
			uri = host + url[1:]
		else:
			uri = host + url

		# check if the URLs has been requested before
		# if it has, don't make the request again, but fetch 
		# it from the cache		
		if not uri in self.cache:
			try:
				# make the request
				r = requests.get(uri, verify=False)

				# calculate the md5 sums for the whole page and 
				# a cleaned version. The cleaned version is used
				# to identify custom 404s
				content = r.content
				r.md5 = hashlib.md5(content).hexdigest().lower()
				r.md5_404 = self.clean_page(r)

				# add to the cache
				self.cache[uri] = r
			except Exception as e:
				print(e)
				r = None
		else:
			r = self.cache[uri]

		return r


	def run(self):
		while not self.kill:
			item = self.queue.get()
			if item is None:
				self.queue.task_done()
				break

			response = self.make_request(item)
			if response is None:
				self.queue.task_done()
				continue

			self.requested.put( (item['fps'], response ) )
			self.queue.task_done()



class Requester(object):
	def __init__(self, host, fps, cache, define_404=False):
		self.fps = fps
		self.threads = len(fps)
		self.workers = []
		self.host = host
		self.define_404 = define_404

		self.cache = cache
		self.results = Results()
		self.queue = queue.Queue()
		self.requested = queue.Queue()
		

	def run(self):

		for fp_list in self.fps:
			self.queue.put({ "host": self.host, "url": fp_list[0]['url'], "fps": fp_list })

		# add 'None' to queue - stops threads when no items are left
		for i in range(self.threads): self.queue.put( None )

		# start the threads
		for i in range(self.threads):
			w = RequesterThread(i, self.queue, self.cache, self.requested)
			w.daemon = True
			self.workers.append(w)
			w.start()

		# join when all work is done
		self.queue.join()

		# the define_404 should only be true during the 
		# preprocessing. 
		if not self.define_404:
			return self.requested

		# if the define_404 flag is set, then the 
		# supplied URLs are to be used for identification of 404 
		# pages
		else:
			error_pages = queue.Queue()
			while self.requested.qsize() > 0:
				_,response = self.requested.get()
				error_pages.put(response.md5_404)

			return error_pages





