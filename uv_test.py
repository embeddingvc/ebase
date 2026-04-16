from asyncio import run
from tools.server import send_message, create_new_post
run(create_new_post('Lobster is great...🦞'))
run(send_message('https://www.linkedin.com/in/ruoqi-huang-b8757b21a/', 'bruh, not doing anything this week, you got any plans?'))

from asyncio import run
from tools.server import fetch_chat_history
run(fetch_chat_history('https://www.linkedin.com/in/jay-sato-263a85270/'))

from asyncio import run
from tools.server import is_first_degree_connection
run(is_first_degree_connection('https://www.linkedin.com/in/daniil-chistoforov/'))