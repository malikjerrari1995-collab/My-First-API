import resend

resend.api_key = "re_C7p7odaG_PaFJUT87ntWC9DHSKa7QJV1F"


r = resend.Emails.send({
    "from": "onboarding@resend.dev",
    "to": "malikjerrari1995@gmail.com",
    "subject": "Test from Expense Tracker!",
    "html": "<h1>It works!</h1><p>Your expense tracker notifications are ready!</p>"
})

print("Email sent!", r)