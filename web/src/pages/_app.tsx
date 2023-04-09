import { AppProps } from 'next/app'
import CssBaseline from '@mui/material/CssBaseline';
import { createTheme, ThemeProvider, type PaletteColorOptions } from '@mui/material/styles';
import Layout from '../components/layout'
import { SessionProvider } from 'next-auth/react';
import '../styles/globals.css';
import { Session } from 'next-auth';

interface PageProps {
  session?: Session
}

const theme = createTheme({
  typography: {
    button: {
      textTransform: 'none'
    }
  }
});

export default function App({
  Component,
  pageProps: { session, ...pageProps }
}: AppProps<PageProps>) {
  return (
    <SessionProvider session={session}>
      <ThemeProvider theme={theme}>
        <CssBaseline>
          <Layout>
            <Component {...pageProps} />
          </Layout>
        </CssBaseline>
      </ThemeProvider>
    </SessionProvider>
  )
}
