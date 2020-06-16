# griffon-poc

![Griffon](http://filer.dev.eng.nutanix.com:8080/Users/sarabjit.saini/azure/Gypful.jpg)

Griffon provider POC level code

Workflow:
1. BMaaS service creates a node instance:
2. BMaaS service calls the image_node proceedure call with
   imaging parameters to initiate node imaging.
3. Image_node proceedure call will stage phoenix on the node and
   kick starts the imaging process. It is also responsible for
   tracking the ndoe state changes as the node imaging proceeds.
4. Image_node will update the node entity status based on actual
   progress of the imaging task.
