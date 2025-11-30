from flask import Flask, render_template, request, redirect, url_for, session, abort
import os
from pymongo import MongoClient, ReturnDocument #, datetime
from bson.objectid import ObjectId
import random

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

def check_name_similarity(user_name, ballot_name, min_length=4):
    """
    Checks if there are 'min_length' continuous matching characters 
    (case-insensitive and removing spaces) between the user name and ballot name.
    """
    
    # 1. Normalize and strip non-alphanumeric characters
    def normalize_string(s):
        return ''.join(filter(str.isalnum, s)).lower()

    normalized_user = normalize_string(user_name)
    normalized_ballot = normalize_string(ballot_name)
    
    if len(normalized_user) < min_length or len(normalized_ballot) < min_length:
        return False # Cannot have a match of min_length
    
    # 2. Generate all substrings of min_length from the user name
    user_substrings = set()
    for i in range(len(normalized_user) - min_length + 1):
        user_substrings.add(normalized_user[i:i+min_length])
        
    # 3. Check if any user substring is present in the ballot name
    for sub in user_substrings:
        if sub in normalized_ballot:
            # Found a match!
            return True
            
    return False



# 1. Admin Entry (Login/Signup)  
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
    """
    # Critical Check 1: Must be logged in
    if 'user_id' not in session:
        return redirect(url_for('user_login'))
        
    # Critical Check 2: User must not have picked yet
    if session.get('has_picked'):
        # Reroute them back to the login, which will handle the reveal
        return redirect(url_for('user_login'))
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
"""
    available_ballots_cursor = ballots_collection.find({'is_picked': False}, {'_id': 1})
    available_ballots = list(available_ballots_cursor)
    random.shuffle(available_ballots)
    num_available = len(available_ballots)

    #  Check for available ballots FIRST, before login ---
    if num_available == 0:
        message = "The current ballot selection session has ended. There are no available ballots remaining."
        return render_template('pick_ballot.html', available_ballots=[], num_available=0, message=message)
    # -------------------------------------------------------------------
        
    # Critical Check 1: Must be logged in (only checked if ballots ARE available)
    if 'user_id' not in session:
        return redirect(url_for('user_login'))
        
    # Critical Check 2: User must not have picked yet
    # We rely on the session state here, but user_login is the central authority 
    if session.get('has_picked'):
        # Reroute them back to the login, which will handle the reveal or state correction
        return redirect(url_for('user_login'))
    
    # If logged in, not picked, and ballots available:
    message = f"There are **{num_available}** private ballots remaining. Choose one!"
    return render_template('pick_ballot.html', available_ballots=available_ballots, num_available=num_available, message=message)

@app.route('/user_login', methods=['GET', 'POST'])
def user_login():
    if session.get('user_id'):
        user_id = ObjectId(session['user_id'])
        user_doc = users_collection.find_one({'_id': ObjectId(session['user_id'])})
        
        # adjusted to prevent indefinite redirects
        if not user_doc:
            session.pop('user_id', None)
            session.pop('has_picked', None)
            
        
        # if user is logged in, check their pick status
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
            # user picked but ballot doc is missing/corrupted
            else:
                session.pop('user_id', None)
                session.pop('has_picked', None)
                return redirect(url_for('user_login'))
            
        # if logged in and has not picked send to selection page
        session['has_picked'] = False
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


# 5. about
@app.route('/about')
def website_about():
    
    return render_template("about.html")

# 6. help
@app.route('/help')
def website_help():
    
    return render_template("help.html")

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
        users_collection.delete_many({}) 
        # ---------------------------------------------------------
        
        # Clear the old ballots
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


# 8. Admin Re-authentication for Confidential Results
@app.route('/admin/reveal_auth', methods=['GET', 'POST'])
def reveal_auth():
    # Must be logged into main admin session first
    if not session.get('admin_logged_in'):
        return redirect(url_for('adminSignup'))
    
    # If already successfully re-authenticated, go straight to results
    if session.get('admin_results_access'):
        return redirect(url_for('reveal_results'))

    if request.method == 'POST':
        username = request.form.get('username')
        password = request.form.get('password')
        admin_user = admins_collection.find_one({'username': username, 'password': password})
        
        if admin_user:
            session['admin_results_access'] = True
            return redirect(url_for('reveal_results'))
        else:
            error = 'Invalid credentials for results access.'
            return render_template('admin_reveal_auth.html', error=error)

    return render_template('admin_reveal_auth.html')

# 9. Admin Confidential Results Display
@app.route('/admin/reveal_results')
def reveal_results():
    if not session.get('admin_logged_in'):
        return redirect(url_for('adminSignup'))
    # Requires successful re-authentication
    if not session.get('admin_results_access'):
        return redirect(url_for('reveal_auth'))
        
    # Prepare the sensitive data
    picked_ballots = list(ballots_collection.find({'is_picked': True}).sort('_id', 1))
    
    # Get user details for mapping
    picked_user_ids = [b['picked_by'] for b in picked_ballots if b.get('picked_by')]
    user_details = {str(user['_id']): user['name'] for user in users_collection.find({'_id': {'$in': picked_user_ids}})}
    
    # Combine ballot and user name
    results_summary = []
    for ballot in picked_ballots:
        user_id_str = str(ballot.get('picked_by')) if ballot.get('picked_by') else None
        user_name = user_details.get(user_id_str, 'N/A (User Deleted or Unknown)')
        results_summary.append({
            'ballot_name': ballot['name'],
            'user_name': user_name
        })
        
    return render_template('admin_reveal_results.html', results_summary=results_summary)



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
    
    user_doc = users_collection.find_one({'_id': picker_user_id}, {'name': 1})
    ballot_to_pick = ballots_collection.find_one({'_id': object_id})
    
    if not user_doc or not ballot_to_pick:
        return render_template('reveal_ballot.html', 
                               ballot_name="Error finding user or ballot information. Please try again.", 
                               is_error=True)
    
    user_name = user_doc['name']
    ballot_name = ballot_to_pick['name']
    
    # Perform the Similarity Check
    if check_name_similarity(user_name, ballot_name):
        return render_template('reveal_ballot.html',
                               ballot_name=f"The ballot name **'{ballot_name}'** is too similar to your name (**'{user_name}'**). Please select a different, random ballot.",
                               is_error=True) 
    
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