import django
from django.core import mail
from django.core.urlresolvers import reverse
from django.test import TestCase
from django.test.utils import override_settings
from django.utils import timezone
from django.utils.unittest import SkipTest

from ..forms import PasswordRecoveryForm, PasswordResetForm
from ..utils import get_user_model

if django.VERSION >= (1, 5):
    from django.contrib.auth.tests.custom_user import (  # noqa
        CustomUser, ExtensionUser)
else:
    CustomUser = None  # noqa
    ExtensionUser = None  # noqa


class CustomUserVariants(type):
    def __new__(cls, name, bases, dct):
        if django.VERSION >= (1, 5):
            for custom_user in ['auth.CustomUser', 'auth.ExtensionUser']:
                suffix = custom_user.lower().replace('.', '_')
                for key, fn in dct.items():
                    if key.startswith('test') and not '_CUSTOM_' in key:
                        name = '{0}_CUSTOM_{1}'.format(key, suffix)
                        dct[name] = override_settings(
                            AUTH_USER_MODEL=custom_user)(fn)
        return super(CustomUserVariants, cls).__new__(cls, name, bases, dct)


def create_user():
    email = 'bar@example.com'
    password = 'pass'
    username = 'foo'
    model = get_user_model()
    kwargs = {}
    args = username, email, password
    if model is CustomUser:
        args = email, timezone.now(), password
    elif model is ExtensionUser:
        kwargs = {'date_of_birth': timezone.now()}
    return get_user_model()._default_manager.create_user(*args, **kwargs)


class FormTests(TestCase):
    __metaclass__ = CustomUserVariants

    def test_username_input(self):
        User = get_user_model()
        if User is CustomUser:
            raise SkipTest('No username field')

        form = PasswordRecoveryForm()
        self.assertFalse(form.is_valid())

        form = PasswordRecoveryForm(data={'username_or_email': 'inexisting'})
        self.assertFalse(form.is_valid())
        self.assertEqual(form.errors['username_or_email'],
                         ["Sorry, this user doesn't exist."])

        create_user()

        form = PasswordRecoveryForm(data={
            'username_or_email': 'foo',
        })
        self.assertTrue(form.is_valid())

        form = PasswordRecoveryForm(data={
            'username_or_email': 'FOO',
        })
        self.assertFalse(form.is_valid())

        form = PasswordRecoveryForm(data={
            'username_or_email': 'FOO',
        }, case_sensitive=False)
        self.assertTrue(form.is_valid())

        form = PasswordRecoveryForm(data={
            'username_or_email': 'bar@example.com',
        })
        self.assertTrue(form.is_valid())

        form = PasswordRecoveryForm(data={
            'username_or_email': 'bar@example.COM',
        })
        self.assertFalse(form.is_valid())

        form = PasswordRecoveryForm(data={
            'username_or_email': 'bar@example.COM',
        }, case_sensitive=False)
        self.assertTrue(form.is_valid())

    def test_form_custom_search(self):
        # Searching only for email does some extra validation
        form = PasswordRecoveryForm(data={
            'username_or_email': 'barexample.com',
        }, search_fields=['email'])
        self.assertFalse(form.is_valid())
        self.assertTrue(form.errors['username_or_email'] in [
            ['Enter a valid email address.'],
            ['Enter a valid e-mail address.'],
        ])

        form = PasswordRecoveryForm(data={
            'username_or_email': 'bar@example.com',
        }, search_fields=['email'])
        self.assertFalse(form.is_valid())
        self.assertEqual(form.errors['username_or_email'],
                         ["Sorry, this user doesn't exist."])

        user = create_user()

        form = PasswordRecoveryForm(data={
            'username_or_email': 'test@example.com',
        }, search_fields=['email'])
        self.assertFalse(form.is_valid())
        self.assertEqual(form.errors['username_or_email'],
                         ["Sorry, this user doesn't exist."])

        # Search by actual email works
        form = PasswordRecoveryForm(data={
            'username_or_email': 'bar@example.com',
        }, search_fields=['email'])
        self.assertTrue(form.is_valid(), form.errors)

        if not hasattr(user, 'username'):
            return  # skip if no username field

        # Now search by username
        user.username = 'username'
        user.save()

        form = PasswordRecoveryForm(data={
            'username_or_email': 'foo@example.com',
        }, search_fields=['username'])
        self.assertFalse(form.is_valid())
        self.assertEqual(form.errors['username_or_email'],
                         ["Sorry, this user doesn't exist."])

        form = PasswordRecoveryForm(data={
            'username_or_email': 'username',
        }, search_fields=['username'])
        self.assertTrue(form.is_valid())

    def test_password_reset_form(self):
        user = create_user()
        old_sha = user.password

        form = PasswordResetForm(user=user)
        self.assertFalse(form.is_valid())

        form = PasswordResetForm(user=user, data={'password1': 'foo'})
        self.assertFalse(form.is_valid())
        self.assertEqual(form.errors['password2'],
                         ['This field is required.'])

        form = PasswordResetForm(user=user, data={'password1': 'foo',
                                                  'password2': 'bar'})
        self.assertFalse(form.is_valid())
        self.assertEqual(form.errors['password2'],
                         ["The two passwords didn't match."])

        form = PasswordResetForm(user=user, data={'password1': 'foo',
                                                  'password2': 'foo'})
        self.assertTrue(form.is_valid())
        self.assertEqual(user.password, old_sha)
        form.save()
        self.assertNotEqual(user.password, old_sha)

    def test_form_commit(self):
        user = create_user()
        old_sha = user.password

        form = PasswordResetForm(user=user, data={'password1': 'foo',
                                                  'password2': 'foo'})
        self.assertTrue(form.is_valid())
        user = form.save(commit=False)
        self.assertEqual(get_user_model()._default_manager.get().password,
                         old_sha)
        self.assertNotEqual(old_sha, user.password)
        user.save()
        self.assertEqual(get_user_model()._default_manager.get().password,
                         user.password)


class ViewTests(TestCase):
    __metaclass__ = CustomUserVariants

    def test_recover(self):
        self.user = create_user()
        url = reverse('password_reset_recover')
        response = self.client.get(url)
        User = get_user_model()

        if User is CustomUser:
            self.assertContains(response, 'Email')
        else:
            self.assertContains(response, 'Username or Email')

        response = self.client.post(url,
                                    {'username_or_email': 'test@example.com'})
        self.assertContains(response, "Sorry, this user")

        self.assertEqual(len(mail.outbox), 0)

        if User is CustomUser:
            value = 'bar@example.com'
        else:
            value = 'foo'
        response = self.client.post(url, {'username_or_email': value},
                                    follow=True)
        self.assertEqual(len(response.redirect_chain), 1)
        self.assertContains(response, 'bar@example.com')

        self.assertEqual(len(mail.outbox), 1)

        message = mail.outbox[0]

        self.assertEqual(message.subject,
                         u'Password recovery on testserver')

        if User is CustomUser:
            self.assertTrue('Dear bar@example.com,' in message.body)
        else:
            self.assertTrue('Dear foo,' in message.body)

        url = message.body.split('http://testserver')[1].split('\n', 1)[0]

        response = self.client.get(url)
        self.assertContains(response, 'New password (confirm)')
        if User is CustomUser:
            self.assertContains(response,
                                'Hi, <strong>bar@example.com</strong>')
        else:
            self.assertContains(response, 'Hi, <strong>foo</strong>')

        data = {'password1': 'foo',
                'password2': 'foo'}
        response = self.client.post(url, data, follow=True)
        self.assertEqual(len(response.redirect_chain), 1)
        self.assertContains(response,
                            "Your password has successfully been reset.")

        self.assertTrue(
            get_user_model()._default_manager.get().check_password('foo'))

    def test_invalid_reset_link(self):
        url = reverse('password_reset_reset', args=['foobar-invalid'])

        response = self.client.get(url)
        self.assertContains(response,
                            "Sorry, this password reset link is invalid")

    def test_email_recover(self):
        self.user = create_user()
        url = reverse('email_recover')
        response = self.client.get(url)
        self.assertNotContains(response, "Username or Email")
        self.assertContains(response, "Email:")

        response = self.client.post(url, {'username_or_email': 'foo'})
        try:
            self.assertContains(response, "Enter a valid email address")
        except AssertionError:
            self.assertContains(response, "Enter a valid e-mail address")

        response = self.client.post(url, {'username_or_email': 'foo@ex.com'})
        self.assertContains(response, "Sorry, this user")

        self.assertEqual(len(mail.outbox), 0)
        response = self.client.post(
            url, {'username_or_email': 'bar@example.com'}, follow=True,
        )
        self.assertEqual(len(mail.outbox), 1)
        self.assertEqual(len(response.redirect_chain), 1)
        self.assertContains(response, 'bar@example.com')

    def test_username_recover(self):
        if get_user_model() is CustomUser:
            raise SkipTest("No username field")
        self.user = create_user()
        url = reverse('username_recover')
        response = self.client.get(url)

        self.assertNotContains(response, "Username or Email")
        self.assertContains(response, "Username:")

        response = self.client.post(url,
                                    {'username_or_email': 'bar@example.com'})
        self.assertContains(response, "Sorry, this user")

        self.assertEqual(len(mail.outbox), 0)
        response = self.client.post(
            url, {'username_or_email': 'foo'}, follow=True,
        )
        self.assertEqual(len(mail.outbox), 1)
        self.assertEqual(len(response.redirect_chain), 1)
        self.assertContains(response, 'foo')

    def test_invalid_signature(self):
        url = reverse('password_reset_sent',
                      kwargs={'signature': 'test@example.com:122323333'})
        response = self.client.get(url)
        self.assertEqual(response.status_code, 404)

    def test_content_redirection(self):
        self.user = create_user()
        url = reverse('email_recover')
        response = self.client.get(url)

        response = self.client.post(
            url, {'username_or_email': 'bar@example.com'}, follow=True,
        )
        self.assertEqual(len(mail.outbox), 1)
        self.assertEqual(len(response.redirect_chain), 1)
        self.assertContains(response, '<strong>bar@example.com</strong>')

        if get_user_model() is CustomUser:
            return  # no username field

        url = reverse('username_recover')
        response = self.client.post(
            url, {'username_or_email': 'foo'}, follow=True,
        )
        self.assertEqual(len(mail.outbox), 2)
        self.assertEqual(len(response.redirect_chain), 1)
        self.assertContains(response, '<strong>foo</strong>')

    def test_insensitive_recover(self):
        self.user = create_user()
        url = reverse('insensitive_recover')
        response = self.client.get(url)
        normalized = '<strong>bar@example.com</strong>'

        User = get_user_model()
        if User is CustomUser:
            self.assertContains(response, 'Email')
        else:
            self.assertContains(response, 'Username or Email')
        self.assertEqual(len(mail.outbox), 0)

        value = 'BAR@example.COM' if User is CustomUser else 'FOO'
        response = self.client.post(url, {'username_or_email': value},
                                    follow=True)
        self.assertEqual(len(mail.outbox), 1)
        self.assertEqual(len(response.redirect_chain), 1)
        self.assertContains(response, normalized)

        response = self.client.post(
            url, {'username_or_email': 'bar@EXAmPLE.coM'}, follow=True,
        )
        self.assertEqual(len(mail.outbox), 2)
        self.assertEqual(len(response.redirect_chain), 1)
        self.assertContains(response, normalized)

        response = self.client.post(
            url, {'username_or_email': 'bar@example.com'}, follow=True,
        )
        self.assertEqual(len(mail.outbox), 3)
        self.assertEqual(len(response.redirect_chain), 1)
        self.assertContains(response, normalized)
