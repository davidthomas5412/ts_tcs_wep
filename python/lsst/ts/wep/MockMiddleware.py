import time, re, unittest

from collections import Iterable

class MockMiddleware(object):
	"""
	A Mock of the Middleware class. The motivation for this mock is to eliminate the SAL dependency.
	"""

	eventStore = dict()
	telemetryStore = dict()
	
	def __init__(self, moduleName):
		"""
		
		Initialize the MockMiddleware class.
		
		Arguments:
			moduleName {[str]} -- The name of module.
		"""
		self.moduleName = moduleName

	def resetTopic(self):
		"""
		
		Reset the topic.
		"""
		return

	def shutDownSal(self):
		"""
		
		Shut down the SAL.
		"""
		return

	def setTimeOut(self, timeout):
		"""
		
		Set the time out.
		
		Arguments:
			timeOut {number} -- Waiting time for time out.
		"""
		return

	def getEvent(self, topic):
		"""
		
		Get the event for specific topic.
		
		Arguments:
			topic {[str]} -- Topic name.
		"""
		return MockMiddleware.eventStore[topic]

	def getTelemetry(self, topic):
		"""
		
		Get the telemetry for specific topic.
		
		Arguments:
			topic {[str]} -- Topic name.
		"""
		return MockMiddleware.telemetryStore[topic]

	def getCommand(self, topic):
		"""
		
		Get the command for specific topic.
		
		Arguments:
			topic {[str]} -- Topic name.
		
		"""
		return

	def issueEvent(self, topic, newData):
		"""
		
		Issue the event for specific topic.
		
		Arguments:
			topic {[str]} -- Topic name.
			newData {[dict]} -- New data for this topic's SAL data instance.
		"""
		MockMiddleware.eventStore[topic] = newData

	def issueTelemetry(self, topic, newData):
		"""
		
		Issue the telemetry for specific topic.
		
		Arguments:
			topic {[str]} -- Topic name.
			newData {[dict]} -- New data for this topic's SAL data instance.

		"""

		MockMiddleware.telemetryStore[topic] = newData

	def issueCommand(self, topic, newData, defaultTimeOut=5):
		"""
		
		Issue the command for specific topic.
		
		Arguments:
			topic {[str]} -- Topic name.
			newData {[dict]} -- New data for this topic's SAL data instance.
		
		Keyword Arguments:
			defaultTimeOut {number} -- Default timeout time if it is not set. (default: {5})
		"""
		return

class MockMiddlewareTest(unittest.TestCase):
	"""
	Test functions in MockMiddleware. 

	"""

	def setUp(self):

		# Module name
		moduleName = "tcsWEP"

		# Declare the MockMiddleware
		self.wepSalIssue = MockMiddleware(moduleName)
		self.wepSalGet = MockMiddleware(moduleName)

	def testTelemetry(self):

		# Reset the topic
		self.wepSalIssue.resetTopic()
		self.wepSalGet.resetTopic()

		# Set the time out
		timeOut = 15
		self.wepSalGet.setTimeOut(timeOut)
		
		# Set the telemetry topic
		topic = "timestamp"

		# Data information of "tcsWEP_timestamp"
		timestamp = 2.0
		newData = {"timestamp": timestamp}

		# Issue the telemetry
		self.wepSalIssue.issueTelemetry(topic, newData)

		# Sleep 1 sec
		time.sleep(1)

		# Get the telemetry
		self.wepSalGet.getTelemetry(topic)

	def testEvent(self):

		# Reset the topic
		self.wepSalIssue.resetTopic()
		self.wepSalGet.resetTopic()

		# Set the event topic
		topic = "summaryState"

		# Event data
		summaryStateValue = 2
		priority = 1
		newData = {"summaryState": summaryStateValue,
				   "priority": priority}

		# Issue the event
		self.wepSalIssue.issueEvent(topic, newData)
		# Sleep 1 sec
		time.sleep(1)

		# Get the event
		self.wepSalGet.getEvent(topic)

	def testCommand(self):

		# Reset the topic
		self.wepSalIssue.resetTopic()
		self.wepSalGet.resetTopic()

		# Set the command topic
		topic = "start"

		# Command data
		settingsToApply = "defaultSetting"
		newData = {"settingsToApply": settingsToApply}

		# Issue the event
		self.wepSalIssue.issueCommand(topic, newData)

		# Sleep 1 sec
		self.wepSalGet.getCommand(topic)

	def tearDown(self):

		# Turn off the sal
		self.wepSalIssue.shutDownSal()
		self.wepSalGet.shutDownSal()

if __name__ == "__main__":

	# Do the unit test
	unittest.main()
