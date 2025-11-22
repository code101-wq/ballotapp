from flask import Flask, render_template, request, redirect, url_for, session, abort
import os
from pymongo import MongoClient, ReturnDocument #, datetime
from bson.objectid import ObjectId
import random

# --- Flask Initialization and MongoDB Setup (No changes needed here) ---
app = Flask(__name__)
app.secret_key = os.urandom(24) 
MONGO_URI = "mongodb://localhost:27017/PrivateBallotDB"
try:
    client = MongoClient(MONGO_URI)
    db = client.get_database("PrivateBallotDB") 
    ballots_collection = db.ballots
    admins_collection = db.admins
    users_collection = db.users
    print("Successfully connected to MongoDB.")
except Exception as e:
    print(f"Error connecting to MongoDB: {e}")
    
#

if admins_collection.count_documents({}) == 0:
    default_admin = { "username":"admin",
                      "password" : "password123" }
    admins_collection.insert_one(default_admin)
# ---

# --- Routes (FIXED ORDER) ---

# 1. Admin Entry (Login/Signup) - MUST be first, as it's in layout.html (and used by dashboard)
@app.route('/signAdmin', methods=['GET', 'POST'])
def adminSignup():
    if session.get('admin_logged_in'):
        return redirect(url_for('admin_dashboard')) 
    # ... rest of the logic
    if request.method == 'POST':
        username = request.form.get('username')
        password = request.form.get('password')
        admin_user = admins_collection.find_one({'username': username, 'password': password})
        if admin_user:
        # if username == 'admin' and password == 'password123':
            session['admin_logged_in'] = True
            return redirect(url_for('admin_dashboard'))
        else:
            error = 'Invalid credentials. Please try again.'
            return render_template('admin_signup.html', error=error)
    return render_template('admin_signup.html')



# 2. Route to display all available ballots - MUST be second, as it's in layout.html
@app.route('/pick_ballot')
def pick_ballot():
    # Critical Check 1: Must be logged in
    if 'user_id' not in session:
        return redirect(url_for('userLogin'))
        
    # Critical Check 2: User must not have picked yet
    if session.get('has_picked'):
        # Reroute them back to the login, which will handle the reveal
        return redirect(url_for('userLogin'))
    # ... logic (check session.get('has_picked'), find ballots, shuffle, render)
    available_ballots_cursor = ballots_collection.find({'is_picked': False}, {'_id': 1})
    available_ballots = list(available_ballots_cursor)
    random.shuffle(available_ballots)
    num_available = len(available_ballots)
    if num_available == 0:
        message = "All ballots have been picked! Session closed."
    else:
        message = f"There are **{num_available}** private ballots remaining. Choose one!"
    return render_template('pick_ballot.html', available_ballots=available_ballots, num_available=num_available, message=message)

@app.route('/user_login', methods=['GET', 'POST'])
def user_login():
    if session.get('user_id'):
        user_id = ObjectId(session['user_id'])
        user_doc = users_collection.find_one({'_id': ObjectId(session['user_id'])})
        if user_doc and user_doc.get('has_picked'):
            # User has picked, find their ballot
            picked_ballot = ballots_collection.find_one({'picked_by': user_id})
            session['has_picked'] = True # Ensure session flag is set
            # Redirect to reveal their *known* ballot
            if picked_ballot:
                return render_template('reveal_ballot.html', 
                                       ballot_name=picked_ballot['name'], 
                                       is_error=False,
                                       is_repeat_view=True)

        return redirect(url_for('pick_ballot'))
    
    if request.method == 'POST':
        user_name = request.form.get('name')
        user_email = request.form.get('email')
        # Check if user already exists
        # 1. Check if user already exists
        existing_user = users_collection.find_one({'email': user_email})
        
        if existing_user:
            # User exists: Use their existing _id
            user_doc = existing_user
        else:
            # New User: Insert and get the document
            new_user_doc = {'name': user_name, 'email': user_email, 'has_picked': False}
            insert_result = users_collection.insert_one(new_user_doc)
            
            # Since we inserted, we fetch the complete document back (optional, but clean)
            user_doc = users_collection.find_one({'_id': insert_result.inserted_id}) 

        
        if user_doc:
            # 2. Set the session user ID using the actual MongoDB ObjectId
            session['user_id'] = str(user_doc['_id'])
            
            # 3. Check picked status and handle routing
            if user_doc.get('has_picked'):
                session['has_picked'] = True
                
                # Find and reveal their ballot
                picked_ballot = ballots_collection.find_one({'picked_by': user_doc['_id']})
                if picked_ballot:
                    return render_template('reveal_ballot.html', 
                                           ballot_name=picked_ballot['name'], 
                                           is_error=False,
                                           is_repeat_view=True)
            else:
                session['has_picked'] = False
                
            return redirect(url_for('pick_ballot'))
        else:
            # This should ideally not happen if insertion/lookup works
            error = 'Could not process user information.'
            return render_template('user_login.html', error=error)
            
    # GET request: Show the login form
    return render_template('user_login.html')
        
# 3. Landing Page - This is the actual rendered template, and it's referenced by 'root'
@app.route('/landing')
def landing():
    return render_template('landing_page.html')


# 4. Root Redirect - Uses 'landing', which is now defined.
@app.route('/')
def root():
    return redirect(url_for('landing'))


# --- Remaining Routes (Order less critical, but generally kept together) ---

# 5. Admin Dashboard (Required by adminSignup)
@app.route('/admin/dashboard')
def admin_dashboard():
    if not session.get('admin_logged_in'):
        return redirect(url_for('adminSignup'))
    # ... rest of the dashboard logic
    picked_user_ids = ballots_collection.distinct('picked_by', {'picked_by': {'$ne': None}})
    user_details = {str(user['_id']): user['name'] for user in users_collection.find({'_id': {'$in': picked_user_ids}})}
    total_ballots = ballots_collection.count_documents({})
    picked_ballots = ballots_collection.count_documents({'is_picked': True})
    available_ballots = total_ballots - picked_ballots
    ballot_results = list(ballots_collection.find().sort('_id', -1))
    return render_template('admin_dashboard.html', total_ballots=total_ballots, picked_ballots=picked_ballots, available_ballots=available_ballots, ballot_results=ballot_results)


# 6. Admin Logout
@app.route('/admin/logout')
def admin_logout():
    session.pop('admin_logged_in', None)
    return redirect(url_for('root'))


# 7. Create Ballots
@app.route('/admin/create_ballots', methods=['GET', 'POST'])
def create_ballots():
    # ... logic ...
    if not session.get('admin_logged_in'):
        return redirect(url_for('adminSignup'))
    
    if request.method == 'POST':
        item_names = request.form.get('item_names')
        ballots_collection.delete_many({}) 
        items = [name.strip() for name in item_names.split('\n') if name.strip()]
        ballot_docs = [{'name': item, 'is_picked': False, 'picked_by': None} for item in items]
        if ballot_docs:
            ballots_collection.insert_many(ballot_docs)
            message = f"Successfully created {len(ballot_docs)} ballot items."
        else:
            message = "No items were entered."
        return render_template('create_ballots.html', message=message)

    sample_items = "Key\nCar\nBook\nHoliday Voucher\nGift Card\nDinner\nNothing" 
    return render_template('create_ballots.html', sample_items=sample_items)


# 8. Process Pick
@app.route('/pick_ballot/<string:ballot_id>', methods=['POST'])
def process_pick(ballot_id):
    # Ensure user is logged in before proceeding
    
    if 'user_id' not in session:
        return redirect(url_for('userLogin'))
    
    # Critical Check 2: Already picked check (second layer of enforcement)
    if session.get('has_picked'):
        return render_template('reveal_ballot.html', 
                               ballot_name="You have already picked a ballot in this session.", 
                               is_error=True)
    try:
        object_id = ObjectId(ballot_id) 
    except Exception:
        return redirect(url_for('pick_ballot'))
    # Check if the user has already picked a ballot
    # This prevents users from picking multiple times
 
    picker_user_id = ObjectId(session['user_id'])
    # Attempt to pick the ballot, ensuring it is NOT picked and the user hasn't picked yet
    # We explicitly look for a user document where 'has_picked' is False before updating
    
    # We rely heavily on the atomic update operation in MongoDB:
    update_result = ballots_collection.find_one_and_update(
        {'_id': object_id, 'is_picked': False},  # Query: Find the specific unpicked ballot
        {'$set': {'is_picked': True, 'picked_by': picker_user_id}}, # Update the ballot status
        return_document=ReturnDocument.AFTER
    )
    
    if update_result:
        # Success! The ballot was picked.
        
        # 1. Update user document to block future picks
        users_collection.update_one(
            {'_id': picker_user_id}, 
            {'$set': {'has_picked': True}}
        )
        # 2. Set session flag
        session['has_picked'] = True
        
        return render_template('reveal_ballot.html', ballot_name=update_result['name'], is_error=False)
    else:
        # Failure: Ballot was already picked or not found
        return render_template('reveal_ballot.html', 
                               ballot_name="SORRY! That ballot was just picked by someone else. Please try again.", 
                               is_error=True)
if __name__ == '__main__':
    print("Application starting... Access at http://127.0.0.1:5000/")
    app.run(debug=True, use_reloader=False)