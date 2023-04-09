import Head from 'next/head';
import AppBar from '@mui/material/AppBar';
import Avatar from '@mui/material/Avatar';
import Container from '@mui/material/Container';
import Stack from '@mui/material/Stack';
import Toolbar from '@mui/material/Toolbar';
import Typography from '@mui/material/Typography';
import Box from '@mui/material/Box';
import Button from '@mui/material/Button';
import Person from '@mui/icons-material/Person';
import IconButton from '@mui/material/IconButton';

export const metadata = {
  title: 'Tabby',
  description: 'A friendly Discord bot'
}

type LayoutProps = {
  children: React.ReactNode,
};

export default function Layout({ children }: LayoutProps) {
  return (
    <>
      <AppBar position='sticky'>
        <Toolbar>
          <Container>
            <Stack direction='row' spacing={1} sx={{ alignItems: 'center' }}>
              <Avatar src='/tabby_icon_light.png' />
              <Typography variant='h5' sx={{ flexGrow: 1, display: 'block' }}>
                Tabby
              </Typography>
              <Button sx={{ color: 'primary.contrastText' }}  endIcon={<Person />}>
                Log In
              </Button>
            </Stack>
          </Container>
        </Toolbar>
      </AppBar>
      <main>
        {children}
      </main>
    </>
  )
}
