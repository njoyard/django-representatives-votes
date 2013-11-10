import os
import sys
import pytz
import urllib
from os.path import join
from datetime import datetime

import ijson
from dateutil.parser import parse

from django.core.management.base import BaseCommand
from django.db import transaction, reset_queries
from django.utils.timezone import make_aware

from representatives.models import Representative
from representatives_votes.models import Proposal, ProposalPart, Vote


def get_or_create(klass, _id=None, **kwargs):
    if _id is None:
        object = klass.objects.filter(**kwargs)
    else:
        object = klass.objects.filter(**{_id : kwargs[_id]})
    if object.exists():
        return object[0]
    else:
        return klass.objects.create(**kwargs)


class Command(BaseCommand):
    args = '<option file>'
    help = 'Import vote of the ep parliaments'

    def handle(self, *args, **options):
        if args:
            json_file = args[0]
        else:
            json_file = retrieve_json()

        print "read file", json_file
        start = datetime.now()
        with transaction.commit_on_success():
            vote_iter = ijson.items(open(json_file), 'item')
            for i, vote in enumerate(vote_iter):
                create_in_db(vote, at=i)
                reset_queries()  # to avoid memleaks in debug mode
        sys.stdout.write("\n")
        print datetime.now() - start


def parse_date(date):
    return make_aware(parse(date), pytz.timezone("Europe/Brussels"))


def create_in_db(proposal_data, at):
    proposal = get_or_create(Proposal, title=proposal_data["title"], date=proposal_data["date"], code_name=proposal_data["code_name"], _id="code_name")

    for at_part, part in enumerate(proposal_data['parts'], 0):
        proposal_part = ProposalPart.objects.filter(
            datetime=make_aware(datetime.fromtimestamp(int(part['datetime']) / 1000), pytz.timezone("Europe/Brussels")),
            subject=part['part'],
            part=part['subject'],
            #description=part[''],
            proposal=proposal,
        )
        if not proposal_part.exists():
            proposal_part = ProposalPart.objects.create(
            datetime=make_aware(datetime.fromtimestamp(int(part['datetime']) / 1000), pytz.timezone("Europe/Brussels")),
            subject=part['part'],
            part=part['subject'],
            #description=part[''],
            proposal=proposal,
        )
        else:
            proposal_part = proposal_part[0]

        to_create_vote = []
        for choice in ('for', 'against', 'abstention'):
            for mep_id in part.get('votes_%s' % choice, []):
                mep = Representative.objects.get(remote_id=mep_id)
                vote = Vote.objects.filter(
                    choice=choice,
                    representative=mep,
                    proposal_part=proposal_part,
                )
                if not vote.exists():
                    to_create_vote.append(Vote(
                        choice=choice,
                        representative=mep,
                        proposal_part=proposal_part,
                    ))

        sys.stdout.write("%s %s/%s       \r" % (at, at_part, len(proposal_data["parts"])))
        sys.stdout.flush()
        Vote.objects.bulk_create(to_create_vote)


def retrieve_json():
    "Download and extract json file from toutatis"
    print "Clean old downloaded files"
    json_file = join("/tmp", "ep_votes.json")
    if os.path.exists(json_file):
        os.remove(json_file)
    print "Download vote data from toutatis"
    urllib.urlretrieve('http://toutatis.mm.staz.be/latest/', json_file)
    return json_file
