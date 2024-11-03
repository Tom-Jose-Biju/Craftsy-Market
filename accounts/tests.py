from django.test import LiveServerTestCase
from selenium import webdriver
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from webdriver_manager.chrome import ChromeDriverManager
from accounts.models import User  # Import your custom User model instead

# Create your tests here.

class AccountsSeleniumTests(LiveServerTestCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        # Setup Chrome options
        chrome_options = Options()
        chrome_options.add_argument("--headless")  # Run in headless mode
        chrome_options.add_argument("--no-sandbox")
        chrome_options.add_argument("--disable-dev-shm-usage")
        chrome_options.add_argument("--remote-debugging-port=9222")
        
        # Setup Chrome webdriver with options
        service = Service(ChromeDriverManager().install())
        cls.selenium = webdriver.Chrome(service=service, options=chrome_options)
        cls.selenium.implicitly_wait(10)

    @classmethod
    def tearDownClass(cls):
        if cls.selenium:
            cls.selenium.quit()
        super().tearDownClass()

    def setUp(self):
        # Create a test user using your custom User model
        self.test_user = User.objects.create_user(
            username='testuser',
            email='test@example.com',
            password='testpass123'
        )

    def test_signup_form(self):
        try:
            # Open the signup page
            self.selenium.get(f'{self.live_server_url}/accounts/signup/')
            
            # Find form elements
            username = self.selenium.find_element(By.NAME, "username")
            email = self.selenium.find_element(By.NAME, "email")
            password1 = self.selenium.find_element(By.NAME, "password1")
            password2 = self.selenium.find_element(By.NAME, "password2")
            submit = self.selenium.find_element(By.CSS_SELECTOR, "button[type='submit']")

            # Fill the form
            username.send_keys("Ann")
            email.send_keys("annrosethomas@gmail.com")
            password1.send_keys("Tom12345")
            password2.send_keys("Tom12345")

            # Submit the form
            submit.click()

            # Wait for redirect and verify success
            WebDriverWait(self.selenium, 10).until(
                EC.url_to_be(f'{self.live_server_url}/')
            )
        except Exception as e:
            self.selenium.save_screenshot('test_signup_error.png')
            raise e

    def test_login_form(self):
        try:
            # Open the login page
            self.selenium.get(f'{self.live_server_url}/accounts/login/')
            
            # Find form elements
            username = self.selenium.find_element(By.NAME, "username")
            password = self.selenium.find_element(By.NAME, "password")
            submit = self.selenium.find_element(By.CSS_SELECTOR, "button[type='submit']")

            # Fill the form
            username.send_keys("Ann")
            password.send_keys("Tom12345")

            # Submit the form
            submit.click()

            # Wait for redirect and verify success
            WebDriverWait(self.selenium, 10).until(
                EC.url_to_be(f'{self.live_server_url}/')
            )
        except Exception as e:
            self.selenium.save_screenshot('test_login_error.png')
            raise e
