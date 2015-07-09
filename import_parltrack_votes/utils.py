# coding: utf-8

# This file is part of django-parltrack-votes.
#
# django-parltrack-votes-data is free software: you can redistribute it and/or modify
# it under the terms of the GNU Affero General Public License as
# published by the Free Software Foundation, either version 3 of
# the License, or any later version.
#
# django-parltrack-votes-data is distributed in the hope that it will
# be useful, but WITHOUT ANY WARRANTY; without even the implied
# warranty of MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.
# See the GNU Affero General Public License for more details.
#
# You should have received a copy of the GNU General Affero Public
# License along with django-parltrack-votes.
# If not, see <http://www.gnu.org/licenses/>.
#
# Copyright (C) 2013 Laurent Peuch <cortex@worlddomination.be>
# Copyright (c) 2015 Arnaud Fabre <af@laquadrature.net>

import re
import json
import functools
import logging

# DateTime tools
from django.utils.timezone import make_aware as date_make_aware
from dateutil.parser import parse as date_parse
from pytz import timezone as date_timezone

from django.db import transaction
from django.utils.encoding import smart_str

from urllib import urlopen

from representatives.models import Mandate, Representative
from representatives_votes.models import Dossier, Proposal, Vote
from import_parltrack_votes.models import Matching

logger = logging.getLogger(__name__)

def _parse_date(date_str):
    return date_make_aware(date_parse(date_str), date_timezone('Europe/Brussels'))

def get_dossier_title(dossier_ref):
    """Fall back on parltrack for dossier data
    """
    logger.debug('Get dossier title from parltrack')
    url = 'http://parltrack.euwiki.org/dossier/%s?format=json' % dossier_ref
    json_file = urlopen(url).read()
    try:
        dossier_json = json.loads(json_file)
    except ValueError:
        logging.warning("Failed to get dossier on parltrack !")
        logging.warning('{}'.format(dossier_ref.encode('utf-8')))
        return None

    return dossier_json['procedure']['title']

def parse_dossier_data(dossier_data):
    """Parse data from parltarck dossier export (1 dossier) Update dossier
    if it existed before, this function goal is to import and update a
    dossier, not to import all parltrack data
    """
    
    dossier, created = Dossier.objects.get_or_create(
        reference=dossier_data['procedure']['reference'],
    )
    
    dossier.title = dossier_data['procedure']['title']
    dossier.link = dossier_data['meta']['source']
    dossier.save()

    logger.info('Dossier: ' + dossier.title.encode('utf-8'))

    # previous_proposals = set(dossier.proposals.all())
    for proposal_data in dossier_data['votes']:
        proposal, created = parse_proposal_data(
            proposal_data,
            dossier
        )
        # if not created:
            # previous_proposals.remove(proposal)

    # Delete proposals that dont belongs to this dossier anymore
    # for proposal in previous_proposals:
        # proposal.delete()

def parse_vote_data(vote_data):
    """
    Parse data from parltrack votes db dumps (1 proposal)
    """
    dossier_ref = vote_data.get('epref', '')
    dossier_title = vote_data.get('eptitle', '')
    proposal_display = '{} ({})'.format(vote_data['title'].encode('utf-8'), vote_data.get('report', '').encode('utf-8'))

    if not dossier_ref:
        logger.warning('No dossier for proposal {}'.format(proposal_display))
        dossier_title = vote_data['title']
        dossier_ref = vote_data.get('report', '')

    dossier, created = Dossier.objects.get_or_create(
        reference=dossier_ref
    )
    
    if created:
        # Try to find dossier title (only for new dossiers)
        if not dossier_title:
            # Fall back on parltrack dossier data
            dossier_title = get_dossier_title(dossier_ref)
            if not dossier_title:
                logger.warning('No dossier title for proposal {}'.format(proposal_display))
                dossier_title = vote_data['title']

        dossier.title = dossier_title
        dossier.link = 'http://www.europarl.europa.eu/oeil/popups/ficheprocedure.do?reference=%s' % dossier_ref
        dossier.save()

    logger.info("\nParsing proposal {}".format(proposal_display))
    logger.info("For dossier {} ({})".format(dossier.title.encode('utf-8'), dossier_ref.encode('utf-8')))

    return parse_proposal_data(
        proposal_data=vote_data,
        dossier=dossier
    )

@transaction.atomic
def parse_proposal_data(proposal_data, dossier):
    """Get or Create a proposal model from raw data"""

    proposal_display = '{} ({})'.format(proposal_data['title'].encode('utf-8'), proposal_data.get('report', '').encode('utf-8'))

    # Should remove this test when parltrack is fixed
    try:
        proposal, created = Proposal.objects.get_or_create(
            dossier=dossier,
            title=proposal_data['title'],
            reference=proposal_data.get('report'),
            datetime=_parse_date(proposal_data['ts']),
            kind=proposal_data.get('issue_type'),
            total_for=int(proposal_data.get('For', {}).get('total', 0)),
            total_abstain=int(proposal_data.get('Abstain', {}).get('total', 0)),
            total_against=int(proposal_data.get('Against', {}).get('total', 0))
        )
    except ValueError as e:
        logger.warning("Can't import proposal {}".format(proposal_display))
        logger.warning("ValueError error({})".format(e))
        return (None, None)

    # We dont import votes if proposal already exists
    if not created:
        logger.info('Return existing proposal {}'.format(proposal_display))
        return (proposal, False)

    positions = ['For', 'Abstain', 'Against']
    logger.info('Looking for votes in proposal {}'.format(proposal_display))
    for position in positions:
        for group_vote_data in proposal_data.get(position, {}).get('groups', {}):
            group_name = group_vote_data['group']
            for vote_data in group_vote_data['votes']:
                if 'orig' in vote_data:
                    representative_name = vote_data['orig']
                elif 'name' in vote_data:
                    representative_name = vote_data['name']
                else:
                    representative_name = vote_data

                if not isinstance(representative_name, unicode):
                    logger.warning("Can't import proposal {}".format(proposal_data.get('report', '').encode('utf-8')))
                    logger.warning("Representative not a str {}".format(representative_name))
                    return (None, None)

                representative = find_matching_representatives_in_db(
                    representative_name, proposal.datetime.date(), group_name
                )

                representative_name_group = '{} ({})'.format(representative_name.encode('utf-8'), group_name.encode('utf-8'))
                
                if representative:
                    Vote.objects.create(
                        proposal=proposal,
                        representative=representative,
                        representative_name=representative_name_group,
                        position=position.lower()
                    )
                else:
                    # Despite all efforts we can not find a matching
                    # representative in db or parltrack
                    Vote.objects.create(
                        proposal=proposal,
                        representative=None,
                        representative_name=representative_name_group,
                        position=position.lower()
                    )

    return (proposal, True)

def memoize(obj):
    """
    memoize decorator for keeping representative matches in cache
    """
    cache = obj.cache = {}

    @functools.wraps(obj)
    def memoizer(*args, **kwargs):
        key = str(args) + str(kwargs)
        if key not in cache:
            cache[key] = obj(*args, **kwargs)
        return cache[key]
    return memoizer

@memoize
def find_matching_representatives_in_db(mep, vote_date, representative_group):
    """
    Find representative remote id from its name, the vote date and the representative group
    it uses the internal db, and if we don’t find him we use the parltrack site
    """
    # Only select representatives that have a country mandate at the vote date
    def representative_filter(**args):
        mandates = Mandate.objects.select_related('representative').filter(
            group__kind='country',
            begin_date__lte=vote_date,
            end_date__gte=vote_date,
            **args
        )
        
        return [mandate.representative for mandate in mandates]

    mep = mep.replace(u"ß", "SS")
    mep = mep.replace("(The Earl of) ", "")

    representative = representative_filter(representative__last_name__iexact=mep)
    if not representative:
        representative = representative_filter(representative__last_name__iexact=re.sub("^DE ", "", mep.upper()))
    if not representative:
        representative = representative_filter(representative__last_name__contains=mep.upper())
    if not representative:
        representative = representative_filter(representative__full_name__contains=re.sub("^MC", "Mc", mep.upper()))
    if not representative:
        representative = representative_filter(representative__full_name__icontains=mep)
    # if not representative:
        # representative = representative_filter(representative__slug__endswith=slugify(mep))

    if representative:
        # TODO Ugly hack, we should handle cases where there are multiple results
        representative = representative[0]
        return representative

    try:
        mep = mep.encode('utf-8')
        # Try by searching in the Matching table, avoid many conexions to parltrack
        matching = Matching.objects.get(mep_name=mep, mep_group=representative_group)
        return matching.representative
    except Matching.DoesNotExist:
        mep_display = "{} ({})".format(smart_str(mep), smart_str(representative_group))
        logger.info("Looking for mep {} on parltrack".format(mep_display))
        url = 'http://parltrack.euwiki.org/mep/%s?format=json' % mep
        
        json_file = urlopen(url).read()
        try:
            mep_ep_json = json.loads(json_file)
        except ValueError:
            logger.warning("Failed to get mep on parltrack : {}".format(mep_display))
            Matching.objects.create(
                mep_name=mep,
                mep_group=representative_group,
            )
            return None

        mep_remote_id = mep_ep_json['UserID']
        representative = Representative.objects.get(
            remote_id=mep_remote_id
        )
        
        Matching.objects.create(
            mep_name=mep,
            mep_group=representative_group,
            representative=representative
        )
        return representative
