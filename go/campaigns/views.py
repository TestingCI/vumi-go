from django.http import Http404
from django.shortcuts import render, redirect
from django.core.urlresolvers import reverse


from .forms import CampaignGeneralForm, CampaignConfigurationForm


def details(request, key=None):
    """
    I guess we would actually use a form here.

    But I don't know how this hooks up with the models;
    So... I'm going to maybe fake it?

    Ok. I won't.

    I'll create a form, but you guys will have to hook it up properly.
    """
    form_general = CampaignGeneralForm()
    form_config = CampaignConfigurationForm()

    if request.POST:

        action = request.POST.get('action')
        if action == 'draft':
            return redirect('conversations:index')
            # save and go back to list.

        # save and go to next step.
        return redirect('campaigns:messages', args=['fakekeydawg'])


    return  render(request, 'campaigns/wizard_1_details.html', {
        'form_general': form_general,
        'form_config': form_config
    })

def messages(request, key):
    pass

    # is this for a conversation or bulk?
    # determine that and redirect.

