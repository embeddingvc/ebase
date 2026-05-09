from asyncio import run
from tools.server import send_message, create_new_post
run(send_message('https://www.linkedin.com/in/jay-sato-263a85270/', 'hi buddy'))
run(create_new_post('Lobster is great...🦞'))

from asyncio import run
from tools.server import fetch_chat_history
run(fetch_chat_history('https://www.linkedin.com/in/daniil-chistoforov/'))
run(fetch_chat_history('https://www.linkedin.com/in/nova-chen-4136833a9/'))
run(fetch_chat_history('https://www.linkedin.com/in/jay-sato-263a85270/'))

from asyncio import run
from tools.server import is_first_degree_connection
run(is_first_degree_connection('https://www.linkedin.com/in/daniil-chistoforov/'))

from asyncio import run
from tools.server import parse_profile
run(parse_profile('https://www.linkedin.com/in/daniil-chistoforov/'))

from asyncio import run
from tools.server import merge_conversation_planner_identity
run(merge_conversation_planner_identity(
    persona_json='{"name":"Test User","role":"Engineer","organization":"Example Co","specialization":"Testing merge tool."}',
    organization_json='{"description":"Primary outreach contact works at Example Co."}',
))