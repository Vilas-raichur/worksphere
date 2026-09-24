from rest_framework import status
from rest_framework.response import Response
from rest_framework.views import APIView

from .serializers import EmployeeCreateSerializer


class EmployeeCreateAPIView(APIView):
    def post(self, request):
        serializer = EmployeeCreateSerializer(
            data=request.data,
            context={"request": request},
        )

        serializer.is_valid(raise_exception=True)

        employee = serializer.save()

        return Response(
            {
                "message": "Employee onboarding record created successfully.",
                "onboarding_reference": employee.onboarding_reference,
                "status": employee.status,
            },
            status=status.HTTP_201_CREATED,
        )