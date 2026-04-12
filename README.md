# CPT_S 421 Team 15 Capstone Project

## Project summary

### One-sentence description of the project

TODO: A 20-second elevator pitch of your project - its core idea summarized in one sentence.

### Additional information about the project

TODO: Write a compelling/creative/informative project description / summary

## Installation

### Prerequisites

TODO: List what a user needs to have installed before running the installation instructions below (e.g., git, which versions of Ruby/Rails)
## Running Models
Project is setup to be able to interact with models modularly. This can be controlled with the file `models.yaml` which determines how to connect to models. At the time of writing this message, only open router models are supported. See an example config below for details on which arguments are required to use models hosted by open router.
```yaml
models:
  embedding:
    class_file: "embedding_openrouter.py"
    class: "EmbeddingOpenRouter"
    kwargs:
      model: "nvidia/llama-nemotron-embed-vl-1b-v2:free"
      temperature: 0
  chatbot:
    class_file: "chatbot_openrouter.py"
    class: "ChatbotOpenRouter"
    kwargs:
      model: "google/gemma-4-26b-a4b-it:free"
      temperature: 0

```
- `models.yaml` is generic so that users may extend the model types to include new models sources as needed, modularity is an important feature of this project!
  - Any class which inherits from `_BaseEmbedding` or `_BaseChatbot` should be compatible with the rest of the project
- root key must always be `models` and contain an entry for both `embedding` and `chatbot` models
- the keys inside of the model type must include the following
  - `class_file`: which is the name of the python file containing the class definition
  - `class`: the name of the python class to use/instantiate
  - `kwargs`: the key word arguments to pass to the class constructor
    - this will be depended on the python class and may very between model hosts!
    - this also leaves the door open for customization based on model and machine as configuration can greatly influence how a model responds

### Add-ons

TODO: List which add-ons are included in the project, and the purpose each add-on serves in your app.

### Installation Steps

TODO: Describe the installation process (making sure you mention `bundle install`).
Instructions need to be such that a user can just copy/paste the commands to get things set up and running.


## Functionality

TODO: Write usage instructions. Structuring it as a walkthrough can help structure this section,
and showcase your features.


## Known Problems

TODO: Describe any known issues, bugs, odd behaviors or code smells.
Provide steps to reproduce the problem and/or name a file or a function where the problem lives.


## Contributing

TODO: Leave the steps below if you want others to contribute to your project.

1. Fork it!
2. Create your feature branch: `git checkout -b my-new-feature`
3. Commit your changes: `git commit -am 'Add some feature'`
4. Push to the branch: `git push origin my-new-feature`
5. Submit a pull request :D

## Additional Documentation

TODO: Provide links to additional documentation that may exist in the repo, e.g.,
  * Sprint reports
  * User links

## License

If you haven't already, add a file called `LICENSE.txt` with the text of the appropriate license.
We recommend using the MIT license: <https://choosealicense.com/licenses/mit/>
