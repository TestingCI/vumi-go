from django import forms
from bootstrap.forms import BootstrapForm

from go.conversation.view_definition import ConversationViewDefinitionBase


class SubscriptionForm(BootstrapForm):
    keyword = forms.CharField()
    operation = forms.ChoiceField(choices=(
            ('subscribe', 'subscribe'),
            ('unsubscribe', 'unsubscribe'),
            ))
    campaign_name = forms.CharField()
    reply_copy = forms.CharField()


SubscriptionFormSet = forms.formsets.formset_factory(
    SubscriptionForm, can_delete=True, extra=1)


class ConversationViewDefinition(ConversationViewDefinitionBase):
    edit_conversation_forms = (
        ('handlers', SubscriptionFormSet),
    )