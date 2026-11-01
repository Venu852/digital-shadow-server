import os
from waitress import serve
from app import create_app

app = create_app()

if __name__ == '__main__':
    port = int(os.environ.get('SHADOW_PORT', 5050))
    print(f'Digital Shadow serving on http://127.0.0.1:{port} (waitress, 8 threads)')
    # Bound to loopback only: public traffic arrives through the tunnel on this machine.
    # Waitress would strip X-Forwarded-For before the app sees it; the app decides itself
    # whether to trust it (SHADOW_CLIENT_IP_HEADER, loopback connections only).
    serve(app, host='127.0.0.1', port=port, threads=8,
          clear_untrusted_proxy_headers=False,
          max_request_body_size=1024 * 1024)
