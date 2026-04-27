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