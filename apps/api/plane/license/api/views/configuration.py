# Copyright (c) 2023-present Dexqbit and contributors
# SPDX-License-Identifier: AGPL-3.0-only
# See the LICENSE file for details.

# Python imports
from smtplib import (
    SMTPAuthenticationError,
    SMTPConnectError,
    SMTPRecipientsRefused,
    SMTPSenderRefused,
    SMTPServerDisconnected,
)

# Django imports
from django.core.mail import BadHeaderError, EmailMultiAlternatives, get_connection
from django.db.models import Q, Case, When, Value

# Third party imports
from rest_framework import status
from rest_framework.response import Response

# Module imports
from .base import BaseAPIView
from plane.license.api.permissions import InstanceAdminPermission
from plane.license.models import InstanceConfiguration
from plane.license.api.serializers import InstanceConfigurationSerializer
from plane.license.utils.encryption import encrypt_data
from plane.utils.cache import cache_response, invalidate_cache
from plane.license.utils.instance_value import get_email_configuration


def _smtp_error_detail(exc):
    detail = getattr(exc, "smtp_error", None) or getattr(exc, "args", None)
    if isinstance(detail, (list, tuple)) and detail:
        detail = detail[-1]
    if isinstance(detail, bytes):
        detail = detail.decode(errors="replace")
    return str(detail) if detail else None


def _resolve_smtp_settings(request_data):
    """
    Merge god-mode form payload with stored instance configuration.

    The test-email UI can run before or without a save; prefer explicit request
    values when present so credentials the admin just typed are actually used.
    """
    (
        stored_host,
        stored_user,
        stored_password,
        stored_port,
        stored_tls,
        stored_ssl,
        stored_from,
    ) = get_email_configuration()

    def pick(key, stored, strip=True):
        if key in request_data and request_data.get(key) is not None:
            value = request_data.get(key)
            if value == "" and stored not in (None, ""):
                # Empty password field means "keep stored secret"
                if key == "EMAIL_HOST_PASSWORD":
                    return stored or ""
            value = "" if value is None else str(value)
            return value.strip() if strip else value
        return "" if stored is None else str(stored)

    email_host = pick("EMAIL_HOST", stored_host)
    email_host_user = pick("EMAIL_HOST_USER", stored_user)
    # Never strip SMTP passwords — spaces can be significant (e.g. app passwords)
    email_host_password = pick("EMAIL_HOST_PASSWORD", stored_password, strip=False)
    email_from = pick("EMAIL_FROM", stored_from)
    email_port_raw = pick("EMAIL_PORT", stored_port) or "587"
    email_use_tls = pick("EMAIL_USE_TLS", stored_tls or "1")
    email_use_ssl = pick("EMAIL_USE_SSL", stored_ssl or "0")

    # Gmail/Google Workspace app passwords are often pasted with spaces; AUTH wants 16 chars.
    host_l = (email_host or "").lower()
    if email_host_password and ("gmail.com" in host_l or "google.com" in host_l):
        email_host_password = "".join(email_host_password.split())

    try:
        email_port = int(str(email_port_raw).strip())
    except (TypeError, ValueError) as exc:
        raise ValueError("EMAIL_PORT must be a number.") from exc

    use_tls = str(email_use_tls) == "1"
    use_ssl = str(email_use_ssl) == "1"

    # TLS and SSL are mutually exclusive in Django's SMTP backend
    if use_tls and use_ssl:
        use_ssl = False

    # Common provider defaults when security mode was left unset / mismatched
    if email_port == 465 and not use_ssl:
        use_ssl = True
        use_tls = False
    elif email_port == 587 and not use_tls and not use_ssl:
        use_tls = True

    if not email_host:
        raise ValueError("EMAIL_HOST is required.")

    return {
        "host": email_host,
        "port": email_port,
        "username": email_host_user or None,
        "password": email_host_password or None,
        "use_tls": use_tls,
        "use_ssl": use_ssl,
        "from_email": email_from or email_host_user or None,
    }


class InstanceConfigurationEndpoint(BaseAPIView):
    permission_classes = [InstanceAdminPermission]

    @cache_response(60 * 60 * 2, user=False)
    def get(self, request):
        instance_configurations = InstanceConfiguration.objects.all()
        serializer = InstanceConfigurationSerializer(instance_configurations, many=True)
        return Response(serializer.data, status=status.HTTP_200_OK)

    @invalidate_cache(path="/api/instances/configurations/", user=False)
    @invalidate_cache(path="/api/instances/", user=False)
    def patch(self, request):
        configurations = InstanceConfiguration.objects.filter(key__in=request.data.keys())

        bulk_configurations = []
        for configuration in configurations:
            raw_value = request.data.get(configuration.key, configuration.value)
            value = "" if raw_value is None else str(raw_value)
            # Do not strip encrypted secrets — passwords may include meaningful spaces
            if not configuration.is_encrypted:
                value = value.strip()
            if configuration.is_encrypted:
                configuration.value = encrypt_data(value)
            else:
                configuration.value = value
            bulk_configurations.append(configuration)

        InstanceConfiguration.objects.bulk_update(bulk_configurations, ["value"], batch_size=100)

        serializer = InstanceConfigurationSerializer(configurations, many=True)
        return Response(serializer.data, status=status.HTTP_200_OK)


class DisableEmailFeatureEndpoint(BaseAPIView):
    permission_classes = [InstanceAdminPermission]

    @invalidate_cache(path="/api/instances/", user=False)
    def delete(self, request):
        try:
            InstanceConfiguration.objects.filter(
                Q(
                    key__in=[
                        "EMAIL_HOST",
                        "EMAIL_HOST_USER",
                        "EMAIL_HOST_PASSWORD",
                        "ENABLE_SMTP",
                        "EMAIL_PORT",
                        "EMAIL_FROM",
                    ]
                )
            ).update(value=Case(When(key="ENABLE_SMTP", then=Value("0")), default=Value("")))
            return Response(status=status.HTTP_200_OK)
        except Exception:
            return Response(
                {"error": "Failed to disable email configuration"},
                status=status.HTTP_400_BAD_REQUEST,
            )


class EmailCredentialCheckEndpoint(BaseAPIView):
    def post(self, request):
        receiver_email = request.data.get("receiver_email", False)
        if not receiver_email:
            return Response(
                {"error": "Receiver email is required"},
                status=status.HTTP_400_BAD_REQUEST,
            )

        try:
            smtp = _resolve_smtp_settings(request.data)
        except ValueError as exc:
            return Response({"error": str(exc)}, status=status.HTTP_400_BAD_REQUEST)

        connection = get_connection(
            host=smtp["host"],
            port=smtp["port"],
            username=smtp["username"],
            password=smtp["password"],
            use_tls=smtp["use_tls"],
            use_ssl=smtp["use_ssl"],
            timeout=30,
        )

        subject = "Email Notification from Dexi"
        message = "This is a sample email notification sent from Dexi."
        try:
            msg = EmailMultiAlternatives(
                subject=subject,
                body=message,
                from_email=smtp["from_email"],
                to=[receiver_email],
                connection=connection,
            )
            msg.send(fail_silently=False)
            return Response({"message": "Email successfully sent."}, status=status.HTTP_200_OK)
        except BadHeaderError:
            return Response({"error": "Invalid email header."}, status=status.HTTP_400_BAD_REQUEST)
        except SMTPAuthenticationError as exc:
            detail = _smtp_error_detail(exc)
            host = (request.data.get("EMAIL_HOST") or "").lower()
            is_google = "gmail.com" in host or "google.com" in host or (detail and "gsmtp" in detail.lower())
            error = "Invalid credentials provided"
            if is_google:
                error = (
                    "Google rejected these SMTP credentials. "
                    "A normal Google account password will not work. "
                    "Use a Google App Password (if enabled), or configure Google Workspace "
                    "SMTP relay (smtp-relay.gmail.com) and point Host to that relay."
                )
            return Response(
                {
                    "error": error,
                    **({"detail": detail} if detail else {}),
                },
                status=status.HTTP_400_BAD_REQUEST,
            )
        except SMTPConnectError as exc:
            detail = _smtp_error_detail(exc)
            return Response(
                {
                    "error": "Could not connect with the SMTP server.",
                    **({"detail": detail} if detail else {}),
                },
                status=status.HTTP_400_BAD_REQUEST,
            )
        except SMTPSenderRefused as exc:
            detail = _smtp_error_detail(exc)
            return Response(
                {
                    "error": "From address is invalid.",
                    **({"detail": detail} if detail else {}),
                },
                status=status.HTTP_400_BAD_REQUEST,
            )
        except SMTPServerDisconnected:
            return Response(
                {"error": "SMTP server disconnected unexpectedly."},
                status=status.HTTP_400_BAD_REQUEST,
            )
        except SMTPRecipientsRefused:
            return Response(
                {"error": "All recipient addresses were refused."},
                status=status.HTTP_400_BAD_REQUEST,
            )
        except TimeoutError:
            return Response(
                {"error": "Timeout error while trying to connect to the SMTP server."},
                status=status.HTTP_400_BAD_REQUEST,
            )
        except ConnectionError:
            return Response(
                {"error": "Network connection error. Please check your internet connection."},
                status=status.HTTP_400_BAD_REQUEST,
            )
        except Exception as exc:
            return Response(
                {
                    "error": "Could not send email. Please check your configuration",
                    "detail": str(exc),
                },
                status=status.HTTP_400_BAD_REQUEST,
            )
