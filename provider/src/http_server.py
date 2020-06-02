from flask import Flask, escape, Response, request
app = Flask(__name__)

@app.route('/griffon/log', methods=['POST', 'GET'])
def logs():
  print("{}".format(request.data))
  return Response("Received logs successfully")

if __name__ == '__main__':
    app.run(host="10.41.26.183", port=8080)
