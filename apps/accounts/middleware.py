from urllib.parse import urlsplit

from django.http import HttpResponse
from django.urls import reverse


class HtmxLoginRedirectMiddleware:
    """
    @login_required's normal 302 to the login page works for full-page
    navigations, but the browser's XHR follows a same-origin 302
    transparently before htmx ever sees it - htmx.js only gets the final
    200 response (the login page HTML) and swaps it into the target
    fragment instead of navigating, e.g. the "Отделы"/workspace/table
    panels rendering a login form in place of their content when an
    account is blocked mid-session.

    Setting the HX-Redirect *response header* would be the natural fix,
    but it's just as invisible to htmx as the body: the browser already
    consumed the 302 while following it, so the header never reaches JS.
    Replacing the redirect with a non-3xx response (401) stops the browser
    from auto-following it, so htmx.js sees this response directly and
    honors HX-Redirect regardless of status code, doing a real full-page
    redirect instead of a fragment swap.
    """

    def __init__(self, get_response):
        self.get_response = get_response
        self.login_path = reverse("login").rstrip("/")

    def __call__(self, request):
        response = self.get_response(request)
        if (
            request.headers.get("HX-Request") == "true"
            and response.status_code in (301, 302)
            and urlsplit(response.get("Location", "")).path.rstrip("/") == self.login_path
        ):
            redirect_to = response["Location"]
            response = HttpResponse(status=401)
            response["HX-Redirect"] = redirect_to
        return response
