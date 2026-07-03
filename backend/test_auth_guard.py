import unittest

from app import create_app


class AuthGuardTests(unittest.TestCase):
    def setUp(self):
        self.app = create_app()
        self.app.config["TESTING"] = True
        self.client = self.app.test_client()

    def test_api_requires_login_and_accepts_only_hardcoded_account(self):
        unauth = self.client.get("/api/flow/current")
        self.assertEqual(unauth.status_code, 401)
        self.assertEqual(unauth.get_json()["error"], "auth_required")

        bad_login = self.client.post("/api/auth/login", json={"username": "vk", "password": "bad"})
        self.assertEqual(bad_login.status_code, 401)

        good_login = self.client.post("/api/auth/login", json={"username": "vk", "password": "vk666"})
        self.assertEqual(good_login.status_code, 200)
        self.assertTrue(good_login.get_json()["authenticated"])

        session_resp = self.client.get("/api/auth/session")
        self.assertEqual(session_resp.status_code, 200)
        self.assertTrue(session_resp.get_json()["authenticated"])

        health_resp = self.client.get("/health")
        self.assertNotEqual(health_resp.status_code, 401)

        logout_resp = self.client.post("/api/auth/logout")
        self.assertEqual(logout_resp.status_code, 200)

        after_logout = self.client.get("/api/flow/current")
        self.assertEqual(after_logout.status_code, 401)


if __name__ == "__main__":
    unittest.main()
