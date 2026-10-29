"""Read-only views of tables owned by the Pro3AI services."""

from django.db import models
from django.db.models.expressions import RawSQL


class ServiceModel(models.Model):
    service_db = None  # DATABASES alias of the owning service

    id = models.CharField(primary_key=True, max_length=32)  # UUID hex, CHAR(32)
    created_at = models.DateTimeField()

    class Meta:
        abstract = True
        managed = False


# --- Identity-Backend -------------------------------------------------------

class Organization(ServiceModel):
    service_db = 'identity'
    name = models.CharField(max_length=256)
    org_type = models.CharField(max_length=40)  # PERSONAL / BUSINESS / ENTERPRISE
    subdomain = models.CharField(max_length=255, null=True)
    parent_id = models.CharField(max_length=32, null=True)
    updated_at = models.DateTimeField()
    deleted_at = models.DateTimeField(null=True)

    class Meta(ServiceModel.Meta):
        db_table = 'orgs'

    def __str__(self):
        return self.name


class User(ServiceModel):
    """Name/email are AES-GCM ciphertext; see servicedata/pii.py. Password and
    MFA secrets are deliberately not mapped."""

    service_db = 'identity'
    name_ciphertext = models.CharField(max_length=1024)
    email_ciphertext = models.CharField(max_length=1024)
    salt = models.CharField(max_length=255)
    iv = models.CharField(max_length=255)
    email_verified = models.BooleanField()
    mfa_method = models.CharField(max_length=32, null=True)
    updated_at = models.DateTimeField()
    deleted_at = models.DateTimeField(null=True)

    class Meta(ServiceModel.Meta):
        db_table = 'users_table'


class Member(ServiceModel):
    """One row per (user, org) plus one per (user, programme)."""

    service_db = 'identity'
    user_id = models.CharField(max_length=32)
    org_id = models.CharField(max_length=32)
    programme_id = models.CharField(max_length=32, null=True)
    is_owner = models.BooleanField()
    is_external = models.BooleanField()
    is_org_active = models.BooleanField()
    deleted_at = models.DateTimeField(null=True)

    class Meta(ServiceModel.Meta):
        db_table = 'members'


class Programme(ServiceModel):
    service_db = 'identity'
    name = models.CharField(max_length=256)
    org_id = models.CharField(max_length=32)
    currency = models.CharField(max_length=8, null=True)
    start_date = models.DateField(null=True)
    is_active = models.BooleanField(null=True)
    deleted_at = models.DateTimeField(null=True)

    class Meta(ServiceModel.Meta):
        db_table = 'programmes'


class Subscription(ServiceModel):
    service_db = 'identity'
    org_id = models.CharField(max_length=32)
    tier = models.CharField(max_length=32)  # POC / CORE / CORE_PLUS / ENTERPRISE
    status = models.CharField(max_length=32)
    seats = models.IntegerField(null=True)
    stripe_customer_id = models.CharField(max_length=255, null=True)
    stripe_subscription_id = models.CharField(max_length=255, null=True)
    stripe_price_id = models.CharField(max_length=255, null=True)
    current_period_start = models.DateTimeField(null=True)
    current_period_end = models.DateTimeField(null=True)
    cancel_at_period_end = models.BooleanField(null=True)
    programme_limit_override = models.IntegerField(null=True)
    user_limit_override = models.IntegerField(null=True)
    # Pre-quoted: Django truncates unquoted Oracle names to 30 chars.
    ai_credit_allowance_override_usd = models.FloatField(null=True, db_column='"AI_CREDIT_ALLOWANCE_OVERRIDE_USD"')
    updated_at = models.DateTimeField()
    deleted_at = models.DateTimeField(null=True)

    class Meta(ServiceModel.Meta):
        db_table = 'org_subscriptions'


class BillingEvent(ServiceModel):
    service_db = 'identity'
    stripe_event_id = models.CharField(max_length=255)
    event_type = models.CharField(max_length=255)
    processed_at = models.DateTimeField(null=True)
    outcome = models.CharField(max_length=64, null=True)

    class Meta(ServiceModel.Meta):
        db_table = 'billing_events'


class AuditLog(ServiceModel):
    service_db = 'identity'
    org_id = models.CharField(max_length=32, null=True)
    member_id = models.CharField(max_length=32, null=True)
    action = models.CharField(max_length=64)
    target_type = models.CharField(max_length=64, null=True)
    target_id = models.CharField(max_length=32, null=True)

    class Meta(ServiceModel.Meta):
        db_table = 'audit_logs'


# --- Agent-Backend ----------------------------------------------------------

class AiUsageEvent(ServiceModel):
    service_db = 'agent'
    org_id = models.CharField(max_length=32)
    member_id = models.CharField(max_length=32, null=True)
    feature = models.CharField(max_length=64, null=True)
    model = models.CharField(max_length=128, null=True)
    prompt_tokens = models.IntegerField(null=True)
    completion_tokens = models.IntegerField(null=True)
    cost_usd = models.FloatField(null=True)

    class Meta(ServiceModel.Meta):
        db_table = 'ai_usage_events'


class OrgAiKey(ServiceModel):
    service_db = 'agent'
    org_id = models.CharField(max_length=32)
    limit_usd = models.FloatField(null=True)
    last_usage_usd = models.FloatField(null=True)
    synced_at = models.DateTimeField(null=True)
    disabled = models.BooleanField(null=True)
    deleted_at = models.DateTimeField(null=True)

    class Meta(ServiceModel.Meta):
        db_table = 'org_ai_keys'


class PlanRun(ServiceModel):
    service_db = 'agent'
    org_id = models.CharField(max_length=32)
    member_id = models.CharField(max_length=32, null=True)
    kind = models.CharField(max_length=64, null=True)
    status = models.CharField(max_length=32, null=True)
    deleted_at = models.DateTimeField(null=True)

    class Meta(ServiceModel.Meta):
        db_table = 'plan_runs'


class AgentSession(ServiceModel):
    service_db = 'agent'
    org_id = models.CharField(max_length=32)
    member_id = models.CharField(max_length=32, null=True)
    deleted_at = models.DateTimeField(null=True)

    class Meta(ServiceModel.Meta):
        db_table = 'agent_sessions'


class IngestionLog(ServiceModel):
    service_db = 'agent'
    org_id = models.CharField(max_length=32, null=True)
    document_id = models.CharField(max_length=32, null=True)
    status = models.CharField(max_length=32, null=True)
    pipeline_mode = models.CharField(max_length=32, null=True)

    class Meta(ServiceModel.Meta):
        db_table = 'ingestion_log'


# --- Authorization-Backend --------------------------------------------------

class AccessDecision(ServiceModel):
    service_db = 'authorization'
    member_id = models.CharField(max_length=32, null=True)
    resource_id = models.CharField(max_length=32, null=True)
    action = models.CharField(max_length=32)
    effect = models.CharField(max_length=16)  # ALLOW / DENY
    source = models.CharField(max_length=32, null=True)

    class Meta(ServiceModel.Meta):
        db_table = 'authorization_decision_log'


# --- Document-Backend -------------------------------------------------------

class Document(ServiceModel):
    service_db = 'document'
    organization_id = models.CharField(max_length=32, null=True)
    programme_id = models.CharField(max_length=32, null=True)
    name = models.CharField(max_length=512)
    current_version = models.IntegerField(null=True)
    updated_at = models.DateTimeField()
    deleted_at = models.DateTimeField(null=True)

    class Meta(ServiceModel.Meta):
        db_table = 'documents'


class DocumentVersion(ServiceModel):
    service_db = 'document'
    document_id = models.CharField(max_length=32)
    version = models.IntegerField()
    created_by = models.CharField(max_length=32, null=True)  # member id
    # Byte size lives in a lowercase-quoted "size" column (reserved word) that
    # Django's Oracle backend cannot map (it uppercases names): see VERSION_BYTES.
    deleted_at = models.DateTimeField(null=True)

    class Meta(ServiceModel.Meta):
        db_table = 'document_versions'


VERSION_BYTES = RawSQL('"size"', ())  # DocumentVersion size in bytes; use unjoined only


# --- Planning-Backend -------------------------------------------------------

class WorkItem(ServiceModel):
    service_db = 'planning'
    programme_id = models.CharField(max_length=32, null=True)
    type = models.CharField(max_length=32)
    status = models.CharField(max_length=32, null=True)
    rag = models.CharField(max_length=16, null=True)
    draft = models.BooleanField(null=True)
    updated_at = models.DateTimeField()
    deleted_at = models.DateTimeField(null=True)

    class Meta(ServiceModel.Meta):
        db_table = 'work_items'


# --- Notification-Backend ---------------------------------------------------

class Notification(ServiceModel):
    service_db = 'notification'
    member_id = models.CharField(max_length=32)
    channel = models.CharField(max_length=32, null=True)
    read = models.BooleanField(null=True)
    deleted_at = models.DateTimeField(null=True)

    class Meta(ServiceModel.Meta):
        db_table = 'notifications'
