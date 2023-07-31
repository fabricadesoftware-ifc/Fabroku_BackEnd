# logbook
## Every self-respecting sailor needs to have a logbook;

In this logbook, I'm writing the experiences of developing this tool, my hard times and my successful moments.

First, we need to go back to the idea of this tool, and that's simple:
We needed an application for managing our dokku apps, and after trying some of them, we decided that we would make our own.
And then, the brainstorm started, how to start? what are we achieving with that application?
how can we make it securely? does it need a database?

Well, that's a lot of questions, and we still have not answered a lot of them, but we're getting to it. We've a lot of other applications to base us off, so, we started to analyze the code of them, started to do some little code changes, understanding the logic behind it, and then started our application.

[30/07/2023]
    I need to think the data we're going to use from our clients.
    Like, user can be provided from our authentication service, but what if we need more things?
    Perhaps we're going to have a database in our application for maintaining this data.
    
[30/07/2023]
    Our system uses a ssh connector to connect into our server and then see the dokku information, but, every user will have a ssh connection to our serve? that's not much secure.
    How can we get around this? Single user for the application?
