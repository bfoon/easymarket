from django.core.mail import send_mail
import requests
from django.conf import settings

def send_email(subject, message, recipient_list):
    send_mail(subject, message, settings.DEFAULT_FROM_EMAIL, recipient_list)

def send_whatsapp(phone_number, message):
    try:
        requests.post(
            'https://api.twilio.com/2010-04-01/Accounts/ACa0ca58dacb6f9255c9efb3eeaa17026c/Messages.json',
            data={
                'From': f'whatsapp:{settings.TWILIO_WHATSAPP_NUMBER}',
                'To': f'whatsapp:{phone_number}',
                'Body': message,
            },
            auth=(settings.TWILIO_ACCOUNT_SID, settings.TWILIO_AUTH_TOKEN)
        )
    except Exception as e:
        print("WhatsApp notification failed:", e)

