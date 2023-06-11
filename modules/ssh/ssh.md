# Ssh connector for the remote host

This module will create a ssh connector for the remote host.

It will use your private key, sent to us at the creation of your account.

-- To think about:

- [ ] Is it too much work for creating a ssh connection for every command? -> how can we improve this?
- [ ] Certain people should only edit their own projects at Dokku, how can we make this possible?
- [ ] For general use, like, getting all the projects, there should be a default user to this.
- [ ] Do we need to put effort into security? -> I think so, but how?
