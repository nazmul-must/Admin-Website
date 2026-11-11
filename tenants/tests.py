"""Organization and user pages render real-shaped service data, and degrade when services fail."""

from django.urls import reverse

from servicedata.fake_replies import ORG, ORG_NAME, USER, PageTestCase, replies


class TenantPageTests(PageTestCase):
    """The four tenant pages, end to end through views, selectors and templates."""

    def test_pages_render_with_every_service_up(self) -> None:
        pages = [
            reverse("org-list"),
            reverse("org-detail", args=[ORG]),
            reverse("user-list"),
            reverse("user-detail", args=[USER]),
        ]
        for url in pages:
            with self.subTest(url=url):
                response = self.client.get(url)
                self.assertEqual(response.status_code, 200)
                self.assertContains(response, ORG_NAME)
                self.assertEqual(response.context["down"], [])

    def test_org_detail_shows_limits_and_people(self) -> None:
        response = self.client.get(reverse("org-detail", args=[ORG]))
        self.assertEqual(response.context["user_count"], 1)
        self.assertEqual(response.context["owners"], 0)  # the one membership is programme-scoped
        users = response.context["usage"][0]
        self.assertEqual((users["used"], users["limit"], users["pct"]), (1, 5, 20))
        self.assertContains(response, "Ada Example")

    def test_htmx_search_returns_only_the_table(self) -> None:
        response = self.client.get(reverse("user-list"), {"q": "ada"}, HTTP_HX_REQUEST="true")
        self.assertContains(response, "ada@yopmail.com")
        self.assertNotContains(response, "<html")

    def test_search_and_filters(self) -> None:
        response = self.client.get(reverse("user-list"), {"q": "nobody", "mfa": "on"})
        self.assertEqual(response.context["rows"], [])
        response = self.client.get(reverse("org-list"), {"tier": "CORE", "status": "PAST_DUE"})
        self.assertEqual(len(response.context["rows"]), 1)

    def test_identity_down_shows_unavailable_not_404(self) -> None:
        self.fail_all()
        response = self.client.get(reverse("org-detail", args=[ORG]))
        self.assertEqual(response.status_code, 200)
        self.assertTemplateUsed(response, "tenants/org_unavailable.html")
        self.assertIn("Identity", response.context["down"])

    def test_unknown_org_and_user_are_404(self) -> None:
        self.answer({("identity", "org_detail"): None, ("identity", "user_detail"): None})
        self.assertEqual(self.client.get(reverse("org-detail", args=[ORG])).status_code, 404)
        self.assertEqual(self.client.get(reverse("user-detail", args=[USER])).status_code, 404)

    def test_changed_reply_shape_shows_banner_not_500(self) -> None:
        rows = [{**replies()[("identity", "org_list")][0]}]
        del rows[0]["users"]
        self.answer({("identity", "org_list"): rows})
        response = self.client.get(reverse("org-list"))
        self.assertEqual(response.status_code, 200)
        self.assertIn("Identity", response.context["down"])
