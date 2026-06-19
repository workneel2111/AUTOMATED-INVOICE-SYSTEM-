from flask import Flask, render_template, request, send_file, redirect, url_for, session
from flask_bcrypt import Bcrypt
from pymongo import MongoClient
from bson.objectid import ObjectId
from functools import wraps
from reportlab.pdfgen import canvas
from datetime import datetime, timedelta
import jwt
import os
import qrcode
from dotenv import load_dotenv
import os

load_dotenv()

# ---------------- APP SETUP ----------------
app = Flask(__name__)
app.secret_key = os.getenv("SECRET_KEY")
app.permanent_session_lifetime = timedelta(hours=2)

bcrypt = Bcrypt(app)

# ---------------- DATABASE ----------------
client = MongoClient(os.getenv("MONGO_URI"))
db = client["invoice_db"]
collection = db["invoices"]
users = db["users"]


# ---------------- JWT DECORATOR ----------------
def token_required(func):
    @wraps(func)
    def wrapper(*args, **kwargs):

        token = session.get("token")

        if not token:
            return redirect(url_for("login"))

        try:
            jwt.decode(token, app.secret_key, algorithms=["HS256"])
        except:
            session.pop("token", None)
            return redirect(url_for("login"))

        return func(*args, **kwargs)

    return wrapper


# ---------------- HOME ----------------
@app.route("/")
@token_required
def home():
    total_invoices = collection.count_documents({})
    total_revenue = sum(i.get("total", 0) for i in collection.find())

    return render_template(
        "dashboard.html",
        total_invoices=total_invoices,
        total_revenue=total_revenue
    )
@app.route('/form')
@token_required
def form():
    return render_template('index.html')


# ---------------- GENERATE INVOICE ----------------
@app.route('/generate', methods=['POST'])
@token_required
def generate():

    customer = request.form['customer']
    product = request.form['product']
    quantity = int(request.form['quantity'])
    price = float(request.form['price'])

    total = quantity * price

    invoice = {
        "invoice_number": "INV-" + datetime.now().strftime("%Y%m%d%H%M%S"),
        "invoice_date": datetime.now().strftime("%d-%m-%Y"),
        "customer": customer,
        "product": product,
        "quantity": quantity,
        "price": price,
        "total": total
    }

    collection.insert_one(invoice)

    return render_template("invoice.html", invoice=invoice)
# ---------------- DOWNLOAD PDF ----------------
@app.route("/download/<invoice_number>")
@token_required
def download(invoice_number):

    invoice = collection.find_one({"invoice_number": invoice_number})
    qr_data = f"http://127.0.0.1:5000/verify/{invoice['invoice_number']}"
    qr = qrcode.make(qr_data)

    qr_path = f"invoices/{invoice_number}_qr.png"

    qr.save(qr_path)

    if not invoice:
        return "Invoice not found"

    if not os.path.exists("invoices"):
        os.makedirs("invoices")

    file_path = f"invoices/{invoice_number}.pdf"

    c = canvas.Canvas(file_path)

    c.setFont("Helvetica-Bold", 18)
    c.drawString(200, 800, "INVOICE")

    c.setFont("Helvetica", 12)
    c.drawString(100, 760, f"Invoice: {invoice['invoice_number']}")
    c.drawString(100, 740, f"Date: {invoice['invoice_date']}")
    c.drawString(100, 720, f"Customer: {invoice['customer']}")
    c.drawString(100, 700, f"Product: {invoice['product']}")
    c.drawString(100, 680, f"Qty: {invoice['quantity']}")
    c.drawString(100, 660, f"Price: Rs.{invoice['price']}")
    c.drawString(100, 640, f"Total: Rs.{invoice['total']}")
    c.drawImage(
    qr_path,
    400,
    620,
    width=120,
    height=120
)

    c.save()

    return send_file(file_path, as_attachment=True)
# ---------------- HISTORY ----------------
@app.route("/history")
@token_required
def history():

    search = request.args.get("search")

    if search:
        invoices = list(collection.find({
            "$or": [
                {"invoice_number": {"$regex": search, "$options": "i"}},
                {"customer": {"$regex": search, "$options": "i"}}
            ]
        }))
    else:
        invoices = list(collection.find())

    return render_template("history.html", invoices=invoices)

@app.route("/verify/<invoice_number>")
def verify_invoice(invoice_number):

    invoice = collection.find_one({
        "invoice_number": invoice_number
    })

    if not invoice:
        return render_template(
            "verify.html",
            found=False
        )

    return render_template(
        "verify.html",
        found=True,
        invoice=invoice
    )
# ---------------- DELETE ----------------
@app.route("/delete/<id>")
@token_required
def delete(id):
    collection.delete_one({"_id": ObjectId(id)})
    return redirect(url_for("history"))


# ---------------- EDIT ----------------
@app.route("/edit/<id>")
@token_required
def edit(id):
    invoice = collection.find_one({"_id": ObjectId(id)})
    return render_template("edit.html", invoice=invoice)


@app.route("/update/<id>", methods=["POST"])
@token_required
def update(id):

    quantity = int(request.form["quantity"])
    price = float(request.form["price"])

    collection.update_one(
        {"_id": ObjectId(id)},
        {"$set": {
            "customer": request.form["customer"],
            "product": request.form["product"],
            "quantity": quantity,
            "price": price,
            "total": quantity * price
        }}
    )

    return redirect(url_for("history"))


# ---------------- AUTH: REGISTER ----------------
@app.route("/register", methods=["GET", "POST"])
def register():

    if request.method == "POST":

        hashed = bcrypt.generate_password_hash(request.form["password"]).decode("utf-8")

        users.insert_one({
            "username": request.form["username"],
            "password": hashed
        })

        return redirect(url_for("login"))

    return render_template("register.html")


# ---------------- AUTH: LOGIN ----------------
@app.route("/login", methods=["GET", "POST"])
def login():

    if request.method == "POST":

        user = users.find_one({"username": request.form["username"]})

        if user and bcrypt.check_password_hash(user["password"], request.form["password"]):

            token = jwt.encode({
                "user": user["username"],
                "exp": datetime.utcnow() + timedelta(hours=2)
            }, app.secret_key, algorithm="HS256")

            session["token"] = token
            session.permanent = True

            return redirect(url_for("home"))

        return "Invalid Credentials"

    return render_template("login.html")


# ---------------- RUN ----------------
if __name__ == "__main__":
    app.run(debug=True)