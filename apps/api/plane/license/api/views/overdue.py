# Copyright (c) 2023-present Dexqbit and contributors
# SPDX-License-Identifier: AGPL-3.0-only
# See the LICENSE file for details.

# Python imports
import os

# Django imports
from django.conf import settings
from django.utils import timezone

# Third party imports
from rest_framework import status
from rest_framework.permissions import AllowAny
from rest_framework.response import Response

# Module imports
from plane.db.models import Issue
from plane.db.models.state import StateGroup
from plane.license.api.views.base import BaseAPIView


class OverdueTasksExportEndpoint(BaseAPIView):
    """Return overdue work items in unstarted/started states for an external scheduler."""

    authentication_classes = []
    permission_classes = [AllowAny]

    def get(self, request):
        expected = os.environ.get("OVERDUE_EXPORT_SECRET") or ""
        provided = request.headers.get("X-Overdue-Export-Secret") or ""
        if not expected or provided != expected:
            return Response({"error": "Unauthorized"}, status=status.HTTP_401_UNAUTHORIZED)

        today = timezone.now().date()
        issues = (
            Issue.issue_objects.filter(
                target_date__lt=today,
                state__group__in=[
                    StateGroup.UNSTARTED.value,
                    StateGroup.STARTED.value,
                ],
            )
            .select_related("project", "workspace", "state")
            .prefetch_related("assignees")
            .order_by("target_date", "project__identifier", "sequence_id")
        )

        web_url = (settings.WEB_URL or settings.APP_BASE_URL or "").rstrip("/")
        tasks = []
        for issue in issues:
            workspace_slug = issue.workspace.slug if issue.workspace_id else ""
            project_identifier = issue.project.identifier if issue.project_id else ""
            url = ""
            if web_url and workspace_slug and project_identifier:
                url = f"{web_url}/{workspace_slug}/browse/{project_identifier}-{issue.sequence_id}/"

            tasks.append(
                {
                    "id": str(issue.id),
                    "name": issue.name,
                    "sequence_id": issue.sequence_id,
                    "project_id": str(issue.project_id) if issue.project_id else None,
                    "project_identifier": project_identifier,
                    "project_name": issue.project.name if issue.project_id else None,
                    "workspace_id": str(issue.workspace_id) if issue.workspace_id else None,
                    "workspace_slug": workspace_slug,
                    "state": issue.state.name if issue.state_id else None,
                    "state_group": issue.state.group if issue.state_id else None,
                    "priority": issue.priority,
                    "target_date": issue.target_date.isoformat() if issue.target_date else None,
                    "start_date": issue.start_date.isoformat() if issue.start_date else None,
                    "assignees": [
                        {
                            "id": str(user.id),
                            "email": user.email,
                            "display_name": user.display_name,
                        }
                        for user in issue.assignees.all()
                    ],
                    "url": url,
                }
            )

        now = timezone.now()
        generated_at = now.isoformat()
        if generated_at.endswith("+00:00"):
            generated_at = generated_at.replace("+00:00", "Z")

        return Response(
            {
                "generated_at": generated_at,
                "as_of_date": today.isoformat(),
                "overdue_count": len(tasks),
                "tasks": tasks,
            },
            status=status.HTTP_200_OK,
        )
