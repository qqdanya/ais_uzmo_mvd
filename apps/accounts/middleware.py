from urllib.parse import urlsplit

from django.urls import reverse


class HtmxLoginRedirectMiddleware:
    """
    @login_required's normal 302 to the login page works for full-page
    navigations, but htmx follows redirects itself and swaps the resulting
    login-page HTML into the target fragment (e.g. #workspace) instead of
    navigating the browser - most visibly when an account is blocked
    mid-session and the user's next htmx panel load silently renders a
    login form in place of its content. Turn that redirect into an
    HX-Redirect header so htmx does a real full-page redirect instead.
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
            response["HX-Redirect"] = response["Location"]
        return response
