"""Vercel serverless API — Flask entry point for all /api/* routes."""
from flask import Flask, jsonify, request
from datetime import date, timedelta
import sys, os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from dashboard.data import load_all_data

app = Flask(__name__)


@app.route('/api/data')
def get_data():
    d0 = request.args.get('d0')
    d1 = request.args.get('d1')
    if not d0 or not d1:
        d1 = (date.today() - timedelta(1)).strftime('%Y-%m-%d')
        d0 = (date.today() - timedelta(7)).strftime('%Y-%m-%d')
    try:
        result = load_all_data(d0, d1)
        return jsonify(result)
    except Exception as ex:
        return jsonify({'error': str(ex)}), 500


@app.route('/api/refresh')
def refresh():
    return jsonify({'ok': True})
