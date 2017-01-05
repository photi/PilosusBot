import os
import requests

from flask import jsonify, request, url_for, current_app
from ..models import Permission
from .. import csrf
from . import webhook
from .decorators import permission_required
from .authentication import auth
from ..processing import parse_update, parsed_update_can_be_processed
from ..tasks import celery_chain


TELEGRAM_API_KEY = os.environ.get('TELEGRAM_TOKEN')
URL = "{base}{api}/".format(base='https://api.telegram.org/bot', api=TELEGRAM_API_KEY)


# TODO remove
#bot = telegram.Bot(token=TELEGRAM_API_KEY)



@webhook.route('/{api_key}/<action>'.format(api_key=TELEGRAM_API_KEY), methods=['POST'])
@csrf.exempt
@auth.login_required
@permission_required(Permission.ADMINISTER)
def set_webhook(action):
    """
    Set an URL for Telegram to send POST requests with chat updates.

    $ http --auth email:password --json POST https://bot.address/webhook/api_key/<action> text=Hello
    :param action: str (set, unset)
    :return: JSON
    """

    if action == 'unset':
        # deactivate the bot!
        url = ''
    else:
        # URL to be registered by Telegram
        url = url_for('webhook.handle_webhook', _external=True)

    payload = {'url': url,  # URL Telegram will post updates to
               'max_connections': current_app.config['SERVER_PUBLIC_KEY'],
               'allowed_updates': [],  # if empty list, then all kinds of updates, including messages, get catched.
               }

    # if server lacks valid SSL certificate and uses self-signed cert,
    # it should be uploaded to the Telegram
    # see https://core.telegram.org/bots/webhooks
    if current_app.config['SERVER_PUBLIC_KEY']:
        # open public key in binary mode
        payload['certificate'] = open(current_app.config['SERVER_PUBLIC_KEY'], 'rb')

    # response
    context = {'status': None, 'url': url}

    # make a request to telegram API, catch exceptions if any, return status
    try:
        # set timeout to 120s, since we want server to unset bot even under high load/DDoS
        r = requests.post(URL + 'setWebhook', json=payload, timeout=120)
    except requests.exceptions.RequestException as err:
        context['status'] = str(err)
    else:
        context['status'] = r.text


    return jsonify(context)


@webhook.route('/{api_key}/handle'.format(api_key=TELEGRAM_API_KEY), methods=['POST'])
@csrf.exempt
def handle_webhook():
    """
    Handle POST request sent from Telegram with chat updates.

    :return: JSON
    """

    # update is a Python dict
    update = request.get_json(force=True)

    # parse incoming Update
    parsed_update = parse_update(update)

    # if Update contains 'text', 'chat_id', 'message_id' then process it with Celery chain
    if parsed_update_can_be_processed(parsed_update):
        celery_chain(parsed_update)
    else:
        # otherwise, send an empty dict as an acknowledgement that the Update's received
        pass


    return jsonify(update)


