"""Narrow, documented English checks of claims, not a general semantic judge."""

import re

from trip_agent.tools.context import payload


NUMBER = r"\d[\d,]*(?:\.\d+)?\s*[kK]?"
MONEY = re.compile(rf"(?:USD\s*|US\$\s*|\$\s*)({NUMBER})(?:\s*(?:[-–—‑]|to)\s*(?:USD\s*|\$\s*)?({NUMBER}))?", re.I)
NUMBERS = re.compile(NUMBER)


def amount(value):
    value = value.lower().replace(',', '').replace(' ', '')
    return round(float(value.rstrip('k')) * (1000 if value.endswith('k') else 1), 2)


def money_values(text):
    return {amount(v) for match in MONEY.finditer(text) for v in match.groups() if v}


def budget_claim_checks(response, store):
    checks = []
    request_amounts = set()
    for fact in [response.trip_state.budget, *response.trip_state.preferences]:
        for source_id in fact.source_artifact_ids:
            source = store.read(source_id)
            if source['kind'] == 'requests':
                request_amounts |= money_values(source['data']['text'])
    all_allowed = set(request_amounts)
    budgets = []
    for suggestion in response.suggestions:
        if not suggestion.budget_artifact_id:
            continue
        budget = payload(store.read(suggestion.budget_artifact_id))
        expected = set(budget['total_range_usd'])
        allowed = expected | request_amounts
        for prices in budget['line_items'].values():
            allowed.update(prices)
        for artifact_id in suggestion.evidence_artifact_ids:
            result = payload(store.read(artifact_id))
            for stay in result.get('accommodations', []):
                if stay['id'] == suggestion.accommodation_id:
                    allowed.update(stay['nightly_room_usd'])
            for flight in result.get('flights', []):
                if flight['destination_id'] == suggestion.destination_id:
                    allowed.update(flight['round_trip_person_usd'])
        if budget.get('budget_usd') is not None:
            allowed.add(budget['budget_usd'])
            allowed.update(round(abs(budget['budget_usd'] - total), 2) for total in expected)
        all_allowed |= allowed
        quoted = suggestion.rough_budget
        numbers = {amount(m.group()) for m in NUMBERS.finditer(quoted)}
        checks.append(('Final budget omits or changes the calculated whole-party range', expected <= numbers))
        checks.append(('Final budget contains an unsupported USD amount', money_values(quoted) <= allowed))
        budgets.append(budget)
        checks.extend(scope_checks(quoted + ' ' + suggestion.reasoning, budget))
    if budgets:
        checks.append(('Main reply contains an unsupported USD amount', money_values(response.message) <= all_allowed))
        for budget in budgets:
            checks.extend(scope_checks(response.message, budget))
    return checks


def scope_checks(text, budget):
    if not (budget.get('exclusions') or budget.get('unknown_costs')):
        return []
    unsupported = False
    for sentence in re.split(r'(?<=[.!?])\s+|\n', text.lower()):
        if re.search(r'\b(?:no|without any) (?:excluded|extra|additional) costs\b|\bincluding everything\b', sentence):
            unsupported = True
        for claim in re.finditer(r'\ball[- ]in (?:total|cost|estimate|price)\b|\ball[- ]in\b|\bcomplete (?:trip|whole-trip) (?:total|cost)\b', sentence):
            prefix = sentence[:claim.start()]
            # A limitation or user's budget scope is not an affirmative coverage claim.
            qualified = re.search(r"\b(?:not|isn't|cannot|can't|excludes?|excluding|incomplete)\b", prefix)
            refers_to_budget = re.match(r'\s+budget\b', sentence[claim.end():])
            if not qualified and not refers_to_budget:
                unsupported = True
    return [('Partial estimate described as covering all costs', not unsupported)]


def conflict_checks(response, conflict):
    destination, country = conflict['destination'].lower(), conflict['country'].lower()
    state = response.get('trip_state', {})
    message = response.get('message', '').lower()
    questions = ' '.join(response.get('questions', [])).lower()
    fact = state.get('destination', {})
    retained = destination in str(fact.get('value', '')).lower()
    exclusions = ' '.join(str(f.get('value', '')) for f in state.get('exclusions', [])).lower()
    acknowledges = re.search(r"conflict|incompatib|contradict|mutually exclusive|impossible|(?:can[’']?t|cannot).{0,80}(?:both|without|satisfy)", message)
    false_geography = re.search(rf'\b{re.escape(destination)}\b.{{0,45}}\b(?:outside|not (?:in|part of)|isn.t in)\b.{{0,20}}\b{re.escape(country)}\b', message)
    resolution = (any(term in questions for term in [destination, country, 'requirement', 'constraint'])
                  and bool(re.search(r'which|relax|change|prioriti|reconsider|different|choose|flexib|instead', questions)))
    return [
        ('Conflicting destination requirement not retained', retained and fact.get('status') == 'conflicting'),
        ('Excluded country not retained', country in exclusions),
        ('Reply does not acknowledge the incompatible requirements', bool(acknowledges)),
        ('Reply contradicts the known destination/country relationship', not false_geography),
        ('Unresolved conflict still produced a recommendation', not response.get('suggestions')),
        ('Clarification does not address resolving the conflict', response.get('status') == 'no_match' or resolution),
    ]
