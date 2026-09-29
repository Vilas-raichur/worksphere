from django.urls import path

from .views import (
    EmployeeCreateAPIView,
    OnboardingCorrectionRequestCreateAPIView,
    StartOnboardingAPIView,
    SubmitOnboardingAPIView,
    StartOnboardingCorrectionsAPIView,
    ResubmitOnboardingAPIView,
    VerifyOnboardingCorrectionAPIView,
    ResolveOnboardingCorrectionItemAPIView,
    ApproveOnboardingAPIView,
)


urlpatterns = [
    path(
        "create/",
        EmployeeCreateAPIView.as_view(),
        name="employee-create",
    ),
    path(
        "corrections/create/",
        OnboardingCorrectionRequestCreateAPIView.as_view(),
        name="onboarding-correction-create",
    ),
    path(
    "onboarding/start/",
    StartOnboardingAPIView.as_view(),
    name="onboarding-start",
    ),
    path(
    "onboarding/submit/",
    SubmitOnboardingAPIView.as_view(),
    name="onboarding-submit",
    ),
    path(
    "corrections/start/",
    StartOnboardingCorrectionsAPIView.as_view(),
    name="onboarding-corrections-start",
    ),
    path(
    "onboarding/resubmit/",
    ResubmitOnboardingAPIView.as_view(),
    name="onboarding-resubmit",
    ),
    path(
    "corrections/items/resolve/",
    ResolveOnboardingCorrectionItemAPIView.as_view(),
    name="onboarding-correction-item-resolve",
    ),
    path(
    "onboarding/approve/",
    ApproveOnboardingAPIView.as_view(),
    name="onboarding-approve",
    ),
    path(
    "corrections/verify/",
    VerifyOnboardingCorrectionAPIView.as_view(),
    name="onboarding-correction-verify",
    ),
]