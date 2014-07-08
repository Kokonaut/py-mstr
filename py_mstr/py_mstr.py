import urllib
import requests
import logging

from pyquery import PyQuery as pq

""" This API only supports xml format, as it relies on the format for parsing
    the data into python data structures
"""
BASE_PARAMS = {'taskEnv': 'xml', 'taskContentType': 'xml'}
BASE_URL = 'http://hostname/MicroStrategy/asp/TaskProc.aspx?'
logger = logging.getLogger(__name__)

class MstrClient(object):
    
    def __init__(self, base_url, username, password, project_source,
            project_name):
        
        self._base_url = base_url
        self._session = self._login(project_source, project_name,
                username, password)

    def __del__(self):
        self._logout()

    def __str__(self):
        return 'MstrClient session: %s' % self._session

    def _login(self, project_source, project_name, username, password):
        arguments = {
            'taskId': 'login',
            'server': project_source,
            'project': project_name,
            'userid': username,
            'password': password 
        }
        logger.info("logging in.")
        response = self._request(arguments)
        d = pq(response)
        return d[0][0].find('sessionState').text

    def get_report(self, report_id):
        return Report(self, report_id)

    def get_folder_contents(self, folder_id=None):
        """Returns a dictionary with folder name, GUID, and description.

            args:
                folder_id - id of folder to list contents. If not supplied,
                            returns contents of root folder
            returns:
                dictionary with keys id, name, description, and type 
        """

        arguments = {'sessionState': self._session, 'taskID': 'folderBrowse'}
        if folder_id:
            arguments.update({'folderID': folder_id})
        response = self._request(arguments)
        return self._parse_folder_contents(response)

    def _parse_folder_contents(self, response):
        d = pq(response)
        result = []
        for folder in d('folders').find('obj'):
            result.append({
                'name': folder.find('n').text,
                'description': folder.find('d').text,
                'id': folder.find('id').text,
                'type': folder.find('t').text
            })
        return result

    def list_elements(self, attribute_id):
        """ returns the elements associated with the given attribute id.
            Note that if the call fails (i.e. MicroStrategy returns an
            out of memory stack trace) the returned list is empty

            args:
                attribute_id - the attribute id

            returns:
                a list of strings containing the names for attribute values
        """

        arguments = {'taskId': 'browseElements', 'attributeID': attribute_id,
                'sessionState': self._session}
        response = self._request(arguments)
        return self._parse_elements(response)
        
    def _parse_elements(self, response):
        d = pq(response)
        result = []
        for attr in d('block'):
            if attr.find('n').text:
                result.append(attr.find('n').text)
        return result


    def get_attribute(self, attribute_id):
        """ performs a lookup using MicroStrategy's API to return
            the attribute object for the given attribute id.

            args:
                attribute_id - the attribute guid
            
            returns:
                an Attribute object
        """

        if not attribute_id:
            raise MstrClientException("You must provide an attribute id")
            return
        arguments = {'taskId': 'getAttributeForms', 'attributeID': attribute_id,
                'sessionState': self._session}
        response = self._request(arguments)
        d = pq(response)
        return Attribute(d('dssid')[0].text, d('n')[0].text)

    def _logout(self):
        arguments = {'sessionState': self._session}
        arguments.update(BASE_PARAMS)
        result = self._request(arguments)
        logging.info("logging out returned %s" % result)


    def _request(self, arguments):
        """ assembles the url and performs a get request to
            the MicroStrategy Task Service API

            args:
                arguments - a dictionary mapping get key parameters to values

            returns: the xml text response
        """

        arguments.update(BASE_PARAMS)
        request = self._base_url + urllib.urlencode(arguments)
        logger.info("submitting request %s" % request)
        response = requests.get(request)
        logger.info("received response %s" % response.text)
        return response.text


class Singleton(type):
    def __call__(cls, *args, **kwargs):
        # see if guid is in instances
        if args[0] not in cls._instances:
            cls._instances[args[0]] = super(Singleton, cls).__call__(*args,
                **kwargs)
        return cls._instances[args[0]]


class Attribute(object):
    __metaclass__ = Singleton
    _instances = {}
    def __init__(self, guid, name):
        self.guid = guid
        self.name = name

    def __repr__(self):
        return "<Attribute: guid:%s name:%s>" % (self.guid, self.name)

    def __str__(self):
        return "Attribute: %s - %s" % (self.guid, self.name)


class Metric(object):
    __metaclass__ = Singleton
    _instances = {}
    def __init__(self, guid, name):
        self.guid = guid
        self.name = name

    def __repr__(self):
        return "<Metric: guid:%s name:%s>" % (self.guid, self.name)

    def __str__(self):
        return "Metric: %s - %s" % (self.guid, self.name)


class Prompt(object):

    def __init__(self, guid, prompt_str, required, attribute=None):
        self.guid = guid
        self.prompt_str = prompt_str
        self.attribute = attribute
        self.required = required

    def __repr__(self):
        return "<Prompt: guid:%s string:%s>" % (self.guid, self.prompt_str)

    def __str__(self):
        return "Prompt: %s - %s" % (self.guid, self.prompt_str)


class Report(object):

    def __init__(self, mstr_client, report_id):
        self._mstr_client = mstr_client
        self._id = report_id
        self._args = {'reportID': self._id,'sessionState': mstr_client._session}
        self._attributes = []
        self._metrics = []
        self._headers = []
        self._values = None

    def __str__(self):
        return 'Report with id %s' % self._id

    def get_prompts(self):
        """ returns the prompts associated with this report. If there are
            no prompts, this method returns an error.

            args: None

            returns: a list of Prompt objects
        """

        arguments = {'taskId': 'reportExecute'}
        arguments.update(self._args)
        response = self._mstr_client._request(arguments)
        message = pq(response)('msg')('id')
        if not message:
            logger.debug("failed retrieval of msgID in response %s" % response)
            raise MstrReportException("Error retrieving msgID for report. Most" 
                + " likely the report does not have any prompts.")
            return
        message_id = message[0].text
        arguments = {
            'taskId': 'getPrompts', 
            'objectType': '3',
            'msgID': message_id,
            'sessionState': self._mstr_client._session
        }
        response = self._mstr_client._request(arguments)
        return self._parse_prompts(response)

    def _parse_prompts(self, response):
        """ There are many ways that prompts can be returned. This api
        currently only supports a prompt that uses precreated prompt objects.
        """
        prompts = []
        d = pq(response)[0][0]
        for prompt in d.find('prompts').iterchildren():
            data = prompt.find('orgn')
            attr = None
            if data is not None:
                attr = Attribute(data.find('did').text,
                    data.find('n').text)
            s = prompt.find('mn').text
            required = prompt.find('reqd').text
            guid = prompt.find('loc').find('did').text
            prompts.append(Prompt(guid, s, required, attribute=attr))

        return prompts

    def get_headers(self):
        """ returns the column headers for the report. A report must have
            been executed before calling this method

            args: None
            
            returns: a list of Attribute/Metric objects
        """

        if self._headers:
            return self._headers
        logger.debug("Attempted to retrieve the headers for a report without" + 
                " prior successful execution.")
        raise MstrReportException("Execute a report before viewing the headers")

    def get_attributes(self):
        """ returns the attribute objects for the columns of this report.

            args: None

            returns: list of Attribute objects
        """

        if self._attributes:
            logger.info("Attributes have already been retrieved. Returning " +
                "saved objects.")
            return self._attributes
        arguments = {'taskId': 'browseAttributeForms', 'contentType': 3}
        arguments.update(self._args)
        response = self._mstr_client._request(arguments)
        self._parse_attributes(response)
        return self._attributes

    def _parse_attributes(self, response):
        d = pq(response)
        self._attributes = [Attribute(attr.find('did').text, attr.find('n').text)
                for attr in d('a')]

    def get_values(self):
        if self._values is not None:
            return self._values
        raise MstrReportException("Execute a report before viewing the rows")

    def get_metrics(self):
        if self._metrics:
            return self._metrics
        logger.debug("Attempted to retrieve the metrics for a report without" + 
                " prior successful execution.")
        raise MstrReportException("Execute a report before viewing the metrics")

    def execute(self, start_row=0, start_col=0, max_rows=100000, max_cols=10,
                value_prompt_answers=None, element_prompt_answers=None):
        """
            args:
                start_row - first row number to be returned
                start_col - first column number to be returned
                max_rows - maximum number of rows to return
                max_cols - maximum number of columns to return
                value_prompt_answers - list of (Prompts, strings) in order. If
                    a value is to be left blank, the second argument in the tuple
                    should be the empty string
                element_prompt_answers - element prompt answers represented as a
                    dictionary of Prompt objects (with attr field specified)
                    mapping to a list of attribute values to pass
        """

        arguments = {
            'taskId': 'reportExecute',
            'startRow': start_row,
            'startCol': start_col,
            'maxRows': max_rows,
            'maxCols': max_cols,
            'styleName': 'ReportDataVisualizationXMLStyle',
            'resultFlags' :'393216' # prevent columns from merging
        }
        if value_prompt_answers and element_prompt_answers:
            arguments.update(self._format_xml_prompts(value_prompt_answers,
                element_prompt_answers))
        elif value_prompt_answers:
            arguments.update(self._format_value_prompts(value_prompt_answers))
        elif element_prompt_answers:
            arguments.update(self._format_element_prompts(element_prompt_answers))
        arguments.update(self._args)
        response = self._mstr_client._request(arguments)
        self._values = self._parse_report(response)

    def _format_xml_prompts(self, v_prompts, e_prompts):
        result = "<rsl>"
        for p, s in v_prompts:
            result = result + "<pa pt='5' pin='0' did='" + p.guid + \
                "' tp='10'>" + s + "</pa>"
        result += "</rsl>"
        d = self._format_element_prompts(e_prompts)
        d['promptsAnswerXML'] = result
        return d

    def _format_value_prompts(self, prompts):
        import pudb; pudb.set_trace()

        result = ''
        for i, (prompt, s) in enumerate(prompts):
            if i > 0:
                result += '^'
            if s:
                result += s
            elif not (s == '' and type(prompt) == Prompt):
                raise MstrReportException("Invalid syntax for value prompt " +
                    "answers. Must pass (Prompt, string) tuples")
        return {'valuePromptAnswers': result}

    def _format_element_prompts(self, prompts):
        result = ''
        for prompt, values in prompts.iteritems():
            if result:
                result += ","
            if values:
                prefix = ";" + prompt.attribute.guid + ":"
                result = result + prompt.attribute.guid + ";" + prompt.attribute.guid + ":" + \
                    prefix.join(values)
            else:
                result += prompt.attribute.guid + ";"
        return {'elementsPromptAnswers': result}

    def _parse_report(self, response):
        d = pq(response)
        if self._report_errors(d):
            return None
        if not self._headers:
            self._get_headers(d)
        # iterate through the columns while iterating through the rows
        # and create a list of tuples with the attribute and value for that
        # column for each row
        return [[(self._headers[index], val.text) for index, val
                in enumerate(row.iterchildren())] for row in d('r')]
    
    def _report_errors(self, d):
        """ Performs error checking on the result from the execute
            call. Specifically, this method is looking for the
            <error> tag returned by MicroStrategy.

            Args:
                d - a pyquery object

            Returns:
                a boolean indicating whether or not there was an error.
                If there was an error, an exception should be raised.
        """

        error = d('error')
        if error:
            raise MstrReportException("There was an error running the report." +
                "Microstrategy error message: " + error[0].text)
            return True
        return False          
    
    def _get_headers(self, d):
        obj = d('objects')
        headers = d('headers')
        for col in headers.children():
            elem = obj("[rfd='" + col.attrib['rfd'] + "']")
            if elem('attribute'):
                attr = Attribute(elem.attr('id'), elem.attr('name'))
                self._attributes.append(attr)
                self._headers.append(attr)
            else:
                metric = Metric(elem.attr('id'), elem.attr('name'))
                self._metrics.append(metric)
                self._headers.append(metric)

class MstrClientException(Exception):
    def __init__(self, msg):
        self.msg = msg

    def __str__(self):
        return self.msg

class MstrReportException(Exception):
    def __init__(self, msg):
        self.msg = msg

    def __str__(self):
        return self.msg

