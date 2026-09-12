import csv, os, collections, sys

# Allow path to be passed or use default
repo = r'C:\Users\SNEHA\Buy_or_Wait_repo\dataset'

def load(fname):
    with open(os.path.join(repo, fname), newline='', encoding='utf-8') as f:
        return list(csv.DictReader(f))

profiles = load('financial_profiles.csv')
events = load('financial_events.csv')
rates = load('exchange_rates.csv')
requests = load('requests.csv')
sample_req = load('sample_requests.csv')
payment_opts = load('request_payment_options.csv')
messages = load('messages.csv')
images = load('images.csv')
output_tmpl = load('output.csv')

print('=== FINANCIAL PROFILES ===')
print(f'  Total users: {len(profiles)}')
currencies = collections.Counter(p["home_currency"] for p in profiles)
print(f'  Currencies: {dict(currencies)}')
blank_max_inst = sum(1 for p in profiles if not p["max_installment_months"])
print(f'  No installments (blank max_installment_months): {blank_max_inst}')
priorities = collections.Counter()
for p in profiles:
    for pri in p["financial_priorities"].split("|"):
        if pri:
            priorities[pri] += 1
print(f'  Priority categories (top5): {dict(priorities.most_common(5))}')

print()
print('=== FINANCIAL EVENTS ===')
print(f'  Total events: {len(events)}')
print(f'  Unique users: {len(set(e["user_id"] for e in events))}')
statuses = collections.Counter(e["status"] for e in events)
print(f'  Statuses: {dict(statuses)}')
event_types = collections.Counter(e["event_type"] for e in events)
print(f'  Event types: {dict(event_types)}')
directions = collections.Counter(e["direction"] for e in events)
print(f'  Directions: {dict(directions)}')
flex = collections.Counter(e["flexibility"] for e in events)
print(f'  Flexibility: {dict(flex)}')
blank_amounts = sum(1 for e in events if not e["amount"])
print(f'  Blank amount events: {blank_amounts}')
cats = collections.Counter(e["category"] for e in events)
print(f'  Top categories: {dict(cats.most_common(8))}')
evt_currencies = collections.Counter(e["currency"] for e in events)
print(f'  Currencies in events: {dict(evt_currencies)}')

print()
print('=== EXCHANGE RATES ===')
print(f'  Total rows: {len(rates)}')
currency_pairs = sorted(set((r["from_currency"], r["to_currency"]) for r in rates))
print(f'  Currency pairs: {currency_pairs}')
dates_fx = sorted(set(r["rate_date"] for r in rates))
print(f'  Date range: {dates_fx[0]} to {dates_fx[-1]}')
print(f'  Unique dates: {len(dates_fx)}')

print()
print('=== REQUESTS ===')
print(f'  Total: {len(requests)}')
req_types = collections.Counter(r["request_type"] for r in requests)
print(f'  Request types: {dict(req_types)}')
req_users = set(r["user_id"] for r in requests)
print(f'  Unique users in requests: {len(req_users)}')
partial_allowed = sum(1 for r in requests if r["allows_partial_payment"].lower() == "true")
print(f'  Allows partial payment: {partial_allowed}')
dates = sorted(set(r["request_date"] for r in requests))
print(f'  Request date range: {dates[0]} to {dates[-1]}')

print()
print('=== SAMPLE REQUESTS ===')
print(f'  Total: {len(sample_req)}')
status_dist = collections.Counter(r["affordability_status"] for r in sample_req)
print(f'  Affordability statuses: {dict(status_dist)}')
method_dist = collections.Counter(r["recommended_payment_method"] for r in sample_req)
print(f'  Payment methods: {dict(method_dist)}')

print()
print('=== PAYMENT OPTIONS ===')
print(f'  Total rows: {len(payment_opts)}')
methods = collections.Counter(p["payment_method"] for p in payment_opts)
print(f'  Methods: {dict(methods)}')
opts_per_request = collections.Counter(p["request_id"] for p in payment_opts)
vals = list(opts_per_request.values())
print(f'  Options per request: min={min(vals)} max={max(vals)} avg={sum(vals)/len(vals):.1f}')

print()
print('=== MESSAGES ===')
print(f'  Total: {len(messages)}')
sources = collections.Counter(m["source_type"] for m in messages)
print(f'  Source types: {dict(sources)}')
with_req = sum(1 for m in messages if m["request_id"])
with_event = sum(1 for m in messages if m["related_event_id"])
print(f'  With request_id: {with_req}')
print(f'  With related_event_id: {with_event}')
msg_users = set(m["user_id"] for m in messages)
print(f'  Unique users with messages: {len(msg_users)}')

print()
print('=== IMAGES ===')
print(f'  Total rows in images.csv: {len(images)}')
with_event = sum(1 for i in images if i["related_event_id"])
with_req = sum(1 for i in images if i["request_id"])
print(f'  With related_event_id: {with_event}')
print(f'  With request_id: {with_req}')
img_dir = os.path.join(repo, 'media', 'images')
found = sum(1 for i in images if os.path.exists(os.path.join(img_dir, i['image_id'] + '.png')))
print(f'  PNG files present on disk: {found}/{len(images)}')
for i in images:
    path = os.path.join(img_dir, i['image_id'] + '.png')
    exists = os.path.exists(path)
    size = os.path.getsize(path) if exists else 0
    print(f'    {i["image_id"]}.png: exists={exists}, size={size}B, event={i["related_event_id"]}, req={i["request_id"]}')

print()
print('=== BLANK AMOUNTS -> IMAGES LINKAGE ===')
blank_evt_ids = {e["event_id"] for e in events if not e["amount"]}
print(f'  Events with blank amount: {len(blank_evt_ids)}')
img_by_event = {i["related_event_id"]: i["image_id"] for i in images if i["related_event_id"]}
print(f'  Images linked to events: {len(img_by_event)}')
covered = blank_evt_ids & set(img_by_event.keys())
print(f'  Blank events covered by images: {len(covered)}')
uncovered = blank_evt_ids - set(img_by_event.keys())
print(f'  Blank events WITHOUT image coverage: {len(uncovered)} -> {sorted(uncovered)}')

print()
print('=== OUTPUT TEMPLATE ===')
print(f'  Total rows: {len(output_tmpl)}')
print(f'  Columns: {list(output_tmpl[0].keys()) if output_tmpl else "empty"}')
all_blank = all(not v for row in output_tmpl for k, v in row.items() if k != "request_id")
print(f'  All non-id fields blank: {all_blank}')

print()
print('=== FOREIGN KEY CHECKS ===')
profile_ids = {p["user_id"] for p in profiles}
event_user_ids = {e["user_id"] for e in events}
req_user_ids = {r["user_id"] for r in requests}
missing_profiles_in_events = event_user_ids - profile_ids
missing_profiles_in_requests = req_user_ids - profile_ids
print(f'  Event user_ids not in profiles: {missing_profiles_in_events}')
print(f'  Request user_ids not in profiles: {missing_profiles_in_requests}')
req_ids = {r["request_id"] for r in requests}
opt_req_ids = {p["request_id"] for p in payment_opts}
print(f'  Requests without payment options: {req_ids - opt_req_ids}')
sample_ids = {r["request_id"] for r in sample_req}
print(f'  Sample request IDs in requests.csv: {len(sample_ids & req_ids)} (should be 0)')
print(f'  Total unique request_ids in requests.csv: {len(req_ids)}')
