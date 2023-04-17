# GitGuardian API Remediation Workflow Notebook

## What
A [Jupyter Notebook](https://jupyter.org/install) to learn how to use the GitGuardian API and experiment with automation.

This project contains 2 different notebooks.

1. `API-Remediation-Workflow.ipynb`
This notebook walks through using the GitGuardian API for:  
- Authentication
- Listing triggered incidents
- Assigning incidents
- Unassign incidents
- Resovling incidents
- Ignoring incidents
- Sharing incidents
- Scaning for secrets in an individual file - Note: For this use case, you would be better off with [ggshield](https://github.com/GitGuardian/ggshield) or [py-gitguardian](https://github.com/GitGuardian/py-gitguardian).

2. `GitGuardian-API-Automation-Examples.ipynb`
This notebook shows 3 examples of automating workflows with the API and a little Python logic. 
The automations included are
- 1. Auto-assign the newest incident to a random member of the workspace.
- 2. Auto-assign incident to commit author if they are a member of the workspace.
- 3. Ignore an incident and mark it as a 'test credential' if all occurrences of a secret are in a /test/ directory and invalid.

## How
Prerequisites:
- You will need to have [Jupyter Notebook](https://jupyter.org/install) installed for this to run locally. 
- You will need to have a GitGuardian account with an Owner or Manager role. 
- The Python code requires installing the [`requests` library](https://pypi.org/project/requests/).

1. Clone this repo
2. `cd` to the project folder locally.
3. Run the command `jupyter notebook` in your terminal.
4. Select one of the notebooks listed. If it is your first time, choose the `API-Remediation-Workflow.ipynb` file. 
5. Follow the instructions in the notebook.

