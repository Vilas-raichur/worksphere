from django.test import SimpleTestCase

from employees.serializers import (
    EmployeeOnboardingDetailsSerializer,
    EmployeeOnboardingDetailsSubmissionSerializer,
)


class EmployeeMobileValidationTests(SimpleTestCase):
    serializers_to_test = (
        EmployeeOnboardingDetailsSerializer,
        EmployeeOnboardingDetailsSubmissionSerializer,
    )

    def test_valid_10_digit_indian_mobile_is_accepted(self):
        for serializer_class in self.serializers_to_test:
            with self.subTest(
                serializer=serializer_class.__name__
            ):
                serializer = serializer_class(
                    data={
                        "emergency_contact_mobile": "9876543210"
                    },
                    partial=True,
                )

                self.assertTrue(
                    serializer.is_valid(),
                    serializer.errors,
                )

    def test_9_digit_mobile_is_rejected(self):
        for serializer_class in self.serializers_to_test:
            with self.subTest(
                serializer=serializer_class.__name__
            ):
                serializer = serializer_class(
                    data={
                        "emergency_contact_mobile": "123456789"
                    },
                    partial=True,
                )

                self.assertFalse(serializer.is_valid())
                self.assertIn(
                    "emergency_contact_mobile",
                    serializer.errors,
                )

    def test_mobile_with_letters_is_rejected(self):
        for serializer_class in self.serializers_to_test:
            with self.subTest(
                serializer=serializer_class.__name__
            ):
                serializer = serializer_class(
                    data={
                        "emergency_contact_mobile": "98765ABCDE"
                    },
                    partial=True,
                )

                self.assertFalse(serializer.is_valid())

    def test_mobile_with_country_prefix_is_rejected(self):
        for serializer_class in self.serializers_to_test:
            with self.subTest(
                serializer=serializer_class.__name__
            ):
                serializer = serializer_class(
                    data={
                        "emergency_contact_mobile": "+919876543210"
                    },
                    partial=True,
                )

                self.assertFalse(serializer.is_valid())

    def test_mobile_not_starting_with_6_to_9_is_rejected(self):
        for serializer_class in self.serializers_to_test:
            with self.subTest(
                serializer=serializer_class.__name__
            ):
                serializer = serializer_class(
                    data={
                        "emergency_contact_mobile": "1234567890"
                    },
                    partial=True,
                )

                self.assertFalse(serializer.is_valid())