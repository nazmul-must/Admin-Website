from accounts.models import EDIT_SITE, MANAGE_EMPLOYEES, MANAGER, MONITOR, SUPER_ADMIN, VIEW_SITE

NAV = [
    ('overview', 'Overview', 'layout-dashboard', {'overview'}),
    ('org-list', 'Organizations', 'building-2', {'org-list', 'org-detail'}),
    ('user-list', 'Users', 'users', {'user-list', 'user-detail'}),
    ('growth', 'Growth', 'trending-up', {'growth'}),
    ('billing', 'Billing', 'credit-card', {'billing'}),
    ('ai-usage', 'AI usage', 'sparkles', {'ai-usage'}),
    ('engagement', 'Engagement', 'activity', {'engagement'}),
    ('access', 'Access', 'shield-check', {'access'}),
]


# Super Admin only; pinned to the bottom of the sidebar.
EMPLOYEES = ('employee-list', 'Employees', 'id-card', {'employee-list', 'employee-add', 'employee-edit', 'employee-password'})


def nav(request):
    current = request.resolver_match.url_name if request.resolver_match else None
    items = [(name, label, icon, current in active) for name, label, icon, active in [*NAV, EMPLOYEES]]
    return {
        'nav': items[:-1],
        'employees_nav': items[-1],
        # Breadcrumb label for the current section; detail pages extend it in their template.
        'crumb': next((label for _, label, _, active in items if active), None),
    }


def role(request):
    """Display name of the signed-in user's access level (see accounts/models.py)."""
    user = getattr(request, 'user', None)
    if not user or not user.is_authenticated:
        return {}
    if user.has_perm(MANAGE_EMPLOYEES):  # also true for Django superusers
        label = SUPER_ADMIN
    elif user.has_perm(EDIT_SITE):
        label = MANAGER
    elif user.has_perm(VIEW_SITE):
        label = MONITOR
    else:
        label = 'No role'
    return {'role': label}
