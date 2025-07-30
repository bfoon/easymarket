# marketplace/utils/emailing.py (alternate function)
import os
from email.mime.image import MIMEImage
from django.core.mail import EmailMultiAlternatives

def send_product_email_with_inline_image(to_email, subject, context, image_path):
    """
    context: product_name, product_page_url, wishlist_url, old_price, new_price, preheader, cid
    image_path: local file path to the image
    """
    text_body = (
        f"{context.get('preheader','')}\n\n"
        f"{context['product_name']}\n"
        f"Old price: {context.get('old_price', '')}  New price: {context.get('new_price','')}\n"
        f"View product: {context['product_page_url']}\n"
        f"View your wishlist: {context['wishlist_url']}\n"
    )

    html_body = f"""
    <html><body>
      <p style="display:none">{context.get('preheader','')}</p>
      <a href="{context['product_page_url']}" target="_blank">
        <img src="cid:{context['cid']}" alt="{context['product_name']}" style="max-width:100%;border-radius:8px;">
      </a>
      <h2>{context['product_name']}</h2>
      <p>Price changed from <s>{context.get('old_price','')}</s> to <b>{context.get('new_price','')}</b>.</p>
      <p>
        <a href="{context['product_page_url']}" target="_blank">View Product</a> |
        <a href="{context['wishlist_url']}" target="_blank">Open My Wishlist</a>
      </p>
    </body></html>
    """

    msg = EmailMultiAlternatives(
        subject=subject,
        body=text_body,
        from_email="no-reply@easymarket.com",
        to=[to_email],
    )
    msg.attach_alternative(html_body, "text/html")

    if os.path.exists(image_path):
        with open(image_path, "rb") as f:
            img = MIMEImage(f.read())
            img.add_header("Content-ID", f"<{context['cid']}>")
            img.add_header("Content-Disposition", "inline", filename=os.path.basename(image_path))
            msg.attach(img)

    msg.send(fail_silently=True)
