from dotenv import load_dotenv
load_dotenv()  # loads .env file if it exists

from app import create_app

app = create_app()

if __name__ == "__main__":
    # host="0.0.0.0" makes Atlas reachable on the home network (any device on Wi-Fi)
    app.run(host="0.0.0.0", port=5001, debug=True)
