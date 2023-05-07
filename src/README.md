## Help me in [patreon](https://patreon.com/findit_moe)

This is free, but the server is not.

A simple access user control, this system is used in all my projects to manage
the user access.
Each project has their own database with their own properties, this system only
controls and validates the sessions and access permission by their own token.

### System token

The token used here is a schema developed by myself inspired in JWT and work in
a similar way.

### What is

At the moment, it works with Master -> Real -> Collection -> User.

Where:

* **Master** is the principal user, aka root, this user is unique.
* **Realm** is the project from the _Master_ is possible to have more than one in my case i have tree realms:
    * [findit.moe](https://findit.moe)
    * [shr.wtf](https://shr.wtf)
    * [logger.ws](https://logger.ws)
    * ...
* **Collection** each _Realm_ have their own user collection, a collection can be:
    * Production users
    * Test users
    * Develop users
    * Demo users
    * ...
* **User** Is the user itself

This system can't connect with external APIs or databases. The principal objetive is to
manage the access control in an easy way by middleware in my projects. The user created
here didn't connect with the databases of my projects for that when i create a new user
here, the register will return a user id (sha256 hash), and this will be the identifier
for the user in this database.

This system is not planned to work with the front-end directly, and the idea is to use this
i the back-end

### You will be able to:

* ✅ **User register** (_done_)
* ✅ **User login** (_done_)
* ✅ **User check availability** (_done_)
* ✅ **User access validation** (_done_)

### Master user, Realm and collection manage aren't developed yet

This project pretends to be a complete user management system, and it will
take a while to end with a stable version, but i need the access verification now.

### Visit my other projects

| Project                          | API                                    |
|----------------------------------|----------------------------------------|
| [findit.moe](https://findit.moe) | [findit.arz.ai](https://findit.arz.ai) |
| [shr.wtf](https://shr.wtf)       | [shr.arz.ai](https://shr.arz.ai)       |
| [loggwer.ws](https://logger.ws)  | [log.arz.ai](https://log.arz.ai)       |
