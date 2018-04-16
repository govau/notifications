import uuid

from flask import request, current_app, abort
from flask.wrappers import Request


class CustomRequest(Request):
    _request_id = None

    @property
    def request_id(self):
        if self._request_id is None:
            self._request_id = self._get_request_id(
                'NotifyRequestID',
                'NotifyDownstreamRequestID')
        return self._request_id

    def _get_request_id(self, request_id_header, downstream_header):
        if request_id_header in self.headers:
            return self.headers.get(request_id_header)
        elif downstream_header and downstream_header in self.headers:
            return self.headers.get(downstream_header)
        else:
            return str(uuid.uuid4())


class ResponseHeaderMiddleware(object):
    def __init__(self, app, request_id_header):
        self.app = app
        self.request_id_header = request_id_header

    def __call__(self, environ, start_response):
        def rewrite_response_headers(status, headers, exc_info=None):
            if self.request_id_header not in dict(headers).keys():
                headers = headers + [(
                    self.request_id_header,
                    request.request_id
                )]

            return start_response(status, headers, exc_info)

        return self.app(environ, rewrite_response_headers)


def init_app(app):
    app.request_class = CustomRequest
    app.wsgi_app = ResponseHeaderMiddleware(app.wsgi_app, 'NotifyRequestID')


def check_proxy_header_before_request():
    keys = [
        current_app.config.get('ROUTE_SECRET_KEY_1'),
        current_app.config.get('ROUTE_SECRET_KEY_2'),
    ]
    result, msg = _check_proxy_header_secret(request, keys)

    if not result:
        current_app.logger.warning(msg)
        if current_app.config.get('CHECK_PROXY_HEADER', False):
            abort(403)

    # We need to return None to continue processing the request
    # http://flask.pocoo.org/docs/0.12/api/#flask.Flask.before_request
    return None


def _check_proxy_header_secret(request, secrets, header='X-Custom-Forwarder'):
    if header not in request.headers:
        return False, "Header missing"

    header_secret = request.headers.get(header)
    if not header_secret:
        return False, "Header exists but is empty"

    # if there isn't any non-empty secret configured we fail closed
    if not any(secrets):
        return False, "Secrets are not configured"

    for i, secret in enumerate(secrets):
        if header_secret == secret:
            return True, "Key used: {}".format(i + 1)  # add 1 to make it human-compatible

    return False, "Header didn't match any keys"
